
import matplotlib.pyplot as plt
import numpy as np
from PIL import ImageDraw
import os
import torch


device = "cuda" if torch.cuda.is_available() else "cpu"


def resize_boxes(boxes, orig_size, new_size):
    """Resize boxes to match new image size."""
    orig_h, orig_w = orig_size
    new_h, new_w = new_size
    
    w_scale = new_w / orig_w
    h_scale = new_h / orig_h
    
    return [[
        box[0] * w_scale,
        box[1] * h_scale,
        box[2] * w_scale,
        box[3] * h_scale
    ] for box in boxes]


def analyze_model_memory(model):
    """
    Analyzes model parameters and estimates memory usage.
    Returns detailed statistics about trainable vs non-trainable parameters
    and approximate memory requirements.
    """
    def sizeof_fmt(num, suffix='B'):
        for unit in ['','Ki','Mi','Gi','Ti']:
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}{suffix}"
            num /= 1024.0
    
    # Get parameter counts
    trainable_params = 0
    non_trainable_params = 0
    total_params = 0
    
    # Dictionary to store parameters by module
    module_params = {}
    
    for name, param in model.named_parameters():
        module_name = name.split('.')[0]  # Get top-level module name
        param_count = param.numel()
        total_params += param_count
        
        # Count trainable vs non-trainable
        if param.requires_grad:
            trainable_params += param_count
        else:
            non_trainable_params += param_count
            
        # Add to module counts
        if module_name not in module_params:
            module_params[module_name] = {'trainable': 0, 'non_trainable': 0}
        if param.requires_grad:
            module_params[module_name]['trainable'] += param_count
        else:
            module_params[module_name]['non_trainable'] += param_count
    
    # Calculate memory requirements (rough estimates)
    param_memory = total_params * 2  # 2 bytes for bfloat16
    
    # Optimizer memory (Adam has 2 states per parameter)
    optimizer_memory = trainable_params * 2 * 4  # 4 bytes for float32 optimizer states
    
    # Activation memory (rough estimate - depends on batch size and sequence length)
    batch_size = 1
    seq_length = 128
    # Assuming activations are roughly 2x the trainable parameters per sample
    activation_memory = trainable_params * 2 * batch_size * 2  # 2 bytes per activation
    
    # Gradient memory
    gradient_memory = trainable_params * 4  # 4 bytes for float32 gradients
    
    print("\n=== Model Memory Analysis ===")
    print(f"\nParameter Counts:")
    print(f"Total Parameters: {total_params:,}")
    print(f"Trainable Parameters: {trainable_params:,} ({trainable_params/total_params*100:.1f}%)")
    print(f"Non-trainable Parameters: {non_trainable_params:,} ({non_trainable_params/total_params*100:.1f}%)")
    
    print("\nMemory Requirements (Approximate):")
    print(f"Parameter Memory: {sizeof_fmt(param_memory)}")
    print(f"Optimizer States (Adam): {sizeof_fmt(optimizer_memory)}")
    print(f"Gradient Memory: {sizeof_fmt(gradient_memory)}")
    print(f"Activation Memory (estimated): {sizeof_fmt(activation_memory)}")
    print(f"Total Training Memory (estimated): {sizeof_fmt(param_memory + optimizer_memory + gradient_memory + activation_memory)}")
    
    print("\nParameters by Module:")
    for module_name, counts in module_params.items():
        total = counts['trainable'] + counts['non_trainable']
        print(f"\n{module_name}:")
        print(f"  Total: {total:,}")
        print(f"  Trainable: {counts['trainable']:,} ({counts['trainable']/total*100:.1f}%)")
        print(f"  Non-trainable: {counts['non_trainable']:,} ({counts['non_trainable']/total*100:.1f}%)")
        print(f"  Memory: {sizeof_fmt(total * 2)}")

    return {
        'total_params': total_params,
        'trainable_params': trainable_params,
        'non_trainable_params': non_trainable_params,
        'param_memory': param_memory,
        'optimizer_memory': optimizer_memory,
        'gradient_memory': gradient_memory,
        'activation_memory': activation_memory,
        'total_memory': param_memory + optimizer_memory + gradient_memory + activation_memory,
        'module_params': module_params
    }



def visualize_ground_truth(dataloader, output_dir="output/gt_visualizations", epoch=0):
    """Visualize ground truth bounding boxes and save images."""
    os.makedirs(output_dir, exist_ok=True)
    
    for batch_idx, batch in enumerate(dataloader):
        # btach is just single item its not dataloder but dataset
        image = batch["image"]
        boxes_list = batch["boxes"]
        labels_list = batch["labels"]
        img = image.convert("RGB")
        draw = ImageDraw.Draw(img)
        
        for idx, (box, label) in enumerate(zip(boxes_list, labels_list)):
            # Convert image to PIL format       
            draw.rectangle(box.numpy(), outline="red", width=2)
            draw.text((box[0], box[1]), str(label), fill="red")
            
            # Save the image
        save_path = os.path.join(output_dir, f"epoch_{epoch}_batch_{batch_idx}_img_{idx}.png")
        img.save(save_path)
        print(f"Saved GT visualization: {save_path}")




def visualize_predictions(model, processor, dataset, output_dir="output/pred_visualizations", epoch=0):
    """Visualize model predictions and ground truth on the same image."""
    os.makedirs(output_dir, exist_ok=True)
    model.eval()
    
    def parse_output(text, target_size):
        """Parse the model's output string into bounding boxes and labels."""
        parts = text.split(" ; ")
        boxes = []
        labels = []
        
        for part in parts:
            if "<loc" not in part:
                continue
            locs = part.split(" ")[0]
            label = int(part.split(" ")[-1])
            
            # Convert from 1024-scale back to target size
            coords = [int(loc[5:9]) for loc in locs.split("<loc")[1:]]
            xmin = (coords[0] / 1024) * target_size[1]  # width
            ymin = (coords[1] / 1024) * target_size[0]  # height
            xmax = (coords[2] / 1024) * target_size[1]  # width
            ymax = (coords[3] / 1024) * target_size[0]  # height
            
            boxes.append([xmin, ymin, xmax, ymax])
            labels.append(label)
        
        return boxes, labels
    
    with torch.no_grad():
        image = dataset["image"]
        gt_boxes = dataset["boxes"]
        gt_labels = dataset["labels"]
        
        # Get original and target sizes
        orig_size = image.size[::-1]  # (h, w)


        prefix= f"<image>detect {' ; '.join(str(l) for l in sorted(set(gt_labels)))}"
        # Prepare input for model
        batch = processor(
            text=[prefix],
            images=[image],
            return_tensors="pt",
            padding="longest"
        ).to(device)
        
        batch = {k: v.to(model.device) for k, v in batch.items()}
        # Generate predictions
        outputs = model.generate(
            **batch,
            max_length=128,
            num_beams=5,
            temperature=0.4
        )
        decoded_output = processor.decode(outputs[0], skip_special_tokens=True)
        
        # Parse the output (will get boxes in target size coordinates)
        pred_boxes, pred_labels = parse_output(decoded_output, orig_size)
        
        # Draw on image
        img = image.convert("RGB")
        draw = ImageDraw.Draw(img)
        
        # Draw ground truth in red
        for box, label in zip(gt_boxes, gt_labels):
            draw.rectangle(box, outline="red", width=2)
            draw.text((box[0], box[1]), f"GT:{label}", fill="red")
        
        # Draw predictions in blue
        for box, label in zip(pred_boxes, pred_labels):
            draw.rectangle(box, outline="blue", width=2)
            draw.text((box[0], box[1]), f"Pred:{label}", fill="blue")
        
        # Save the image
        save_path = os.path.join(output_dir, f"epoch_{epoch}_comparison.png")
        img.save(save_path)
        print(f"Saved visualization with both GT and predictions: {save_path}")