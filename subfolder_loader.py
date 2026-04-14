# subfolder_loader.py
import os
import json
import logging
from typing import List, Tuple, Optional
import folder_paths
from PIL import Image
import numpy as np
import torch

# Optional: Add server route for refresh functionality
try:
    import server
    from aiohttp import web
    
    @server.PromptServer.instance.routes.post("/subfolder_loader/refresh")
    async def refresh_file_listings(request):
        """API endpoint to refresh file listings."""
        try:
            data = await request.json()
            node_id = data.get('node_id')
            subfolder = data.get('subfolder', '')
            
            # Get fresh file listings
            input_dir = folder_paths.get_input_directory()
            subfolders = SubfolderImageLoader.get_subfolders(input_dir)
            
            # Get filtered images for the specified subfolder
            if subfolder:
                filtered_images = SubfolderImageLoader.get_images_for_subfolder(subfolder)
            else:
                filtered_images = SubfolderImageLoader.get_images_for_subfolder("")
            
            # Also get all images for client-side filtering if needed
            all_images = SubfolderImageLoader.get_all_images_with_paths(input_dir)
            
            return web.json_response({
                'success': True,
                'subfolders': subfolders,
                'images': all_images,  # All images with paths for client filtering
                'filtered_images': filtered_images,  # Pre-filtered images for the subfolder
                'current_subfolder': subfolder
            })
        except Exception as e:
            logging.error(f"Refresh error: {str(e)}")
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)
except ImportError:
    pass

class SubfolderImageLoader:
    """
    Enhanced image loader with subfolder selection support.
    
    This node allows you to organize your input images into subfolders and then 
    dynamically select images from specific subfolders. First select a subfolder, 
    then choose an image - the image list will automatically filter to show only 
    images from the selected subfolder.
    
    Features:
    - Subfolder navigation within ComfyUI's input directory
    - Dynamic image filtering based on selected subfolder
    - Support for PNG, JPG, JPEG, WebP, BMP, TIFF formats
    - Alpha channel/transparency mask extraction
    - Right-click menu option to refresh file listings
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        
        # Get available subfolders
        subfolders = cls.get_subfolders(input_dir)
        
        # Start with images from root folder (no subfolder selected)
        default_images = cls.get_images_for_subfolder("")
        
        return {
            "required": {
                "subfolder": (subfolders, {
                    "default": None,
                    "tooltip": "Select a subfolder from your input directory. Leave empty for root folder. The image list will update automatically when you change this."
                }),
                "image": (default_images if default_images else [""], {
                    "default": None,
                    "image_upload": True,
                    "tooltip": "Choose an image from the selected subfolder. This list is filtered based on your subfolder selection."
                }),
            },
            "optional": {
                "load_mask": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Extract alpha channel as mask from RGBA/transparent images. Disable if you don't need transparency masks."
                }),
            }
        }
    
    @classmethod 
    def get_images_for_subfolder(cls, subfolder: str = "") -> list:
        """Get filtered images for a specific subfolder."""
        all_images = cls.get_all_images_with_paths(folder_paths.get_input_directory())

        if not subfolder:
            # Only images in root (no slash)
            return [img for img in all_images if "/" not in img]

        prefix = subfolder.rstrip("/") + "/"
        return [
            img for img in all_images
            if img.startswith(prefix) and "/" not in img[len(prefix):]
        ]
    
    @classmethod
    def get_subfolders(cls, base_path: str) -> List[str]:
        """Get list of subfolders in the base directory."""
        subfolders = [""]

        if not os.path.exists(base_path):
            return subfolders

        for root, dirs, _ in os.walk(base_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            rel_root = os.path.relpath(root, base_path)
            if rel_root != ".":
                subfolders.append(rel_root)

        return sorted(subfolders)
    
    @classmethod
    def get_all_images_with_paths(cls, base_path: str) -> List[str]:
        """Get all images with their relative paths."""
        all_images = []
        valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif', '.gif'}

        if not os.path.exists(base_path):
            return all_images

        for root, dirs, files in os.walk(base_path):
            # Skip hidden folders
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            rel_root = os.path.relpath(root, base_path)
            rel_root = "" if rel_root == "." else rel_root

            for file in files:
                ext = os.path.splitext(file.lower())[1]
                if ext in valid_extensions:
                    if rel_root:
                        all_images.append(f"{rel_root}/{file}")
                    else:
                        all_images.append(file)

        return sorted(all_images)
    
    @classmethod
    def get_images_from_folder(cls, folder_path: str) -> List[str]:
        """Get image files from a specific folder."""
        if not os.path.exists(folder_path):
            return []
        
        valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif'}
        images = []
        
        try:
            for file in sorted(os.listdir(folder_path)):
                if os.path.splitext(file.lower())[1] in valid_extensions:
                    images.append(file)
        except PermissionError:
            logging.warning(f"Permission denied accessing {folder_path}")
        
        return images
    
    @classmethod
    def VALIDATE_INPUTS(cls, subfolder="", image="", **kwargs):
        """Validate inputs before execution."""
        if not image:
            return "No image specified"
        
        input_dir = folder_paths.get_input_directory()
        
        # Handle the case where image might contain subfolder prefix
        clean_image = image
        actual_subfolder = subfolder
        
        # If image contains a path separator, extract the subfolder and filename
        if "/" in image:
            parts = image.split("/", 1)
            actual_subfolder, clean_image = parts
        
        # Build the full path
        if actual_subfolder:
            file_path = os.path.join(input_dir, actual_subfolder, clean_image)
        else:
            file_path = os.path.join(input_dir, clean_image)
        
        # Check if file exists
        if not os.path.exists(file_path):
            # Log for debugging
            logging.error(f"File not found: {file_path}")
            logging.error(f"Original - Subfolder: '{subfolder}', Image: '{image}'")
            logging.error(f"Processed - Subfolder: '{actual_subfolder}', Clean image: '{clean_image}'")
            return f"Image file not found: {clean_image}"
        
        # Validate it's within the input directory
        try:
            file_path_abs = os.path.abspath(file_path)
            input_dir_abs = os.path.abspath(input_dir)
            if not file_path_abs.startswith(input_dir_abs):
                return "Invalid file path: outside input directory"
        except Exception:
            return "Invalid file path"
        
        return True
    
    @classmethod
    def IS_CHANGED(cls, subfolder="", image="", **kwargs):
        """Control when node re-executes."""
        if not image:
            return False
        
        try:
            input_dir = folder_paths.get_input_directory()
            
            # If image contains subfolder path
            if "/" in image:
                subfolder, image = image.split("/", 1)

            if subfolder:
                file_path = os.path.join(input_dir, subfolder, image)
            else:
                file_path = os.path.join(input_dir, image)

            if os.path.exists(file_path):
                return os.path.getmtime(file_path)
        except Exception:
            pass

        return False
    
    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "INT", "INT")
    RETURN_NAMES = ("image", "mask", "filename", "width", "height")
    CATEGORY = "image/loaders"
    FUNCTION = "load_image"
    
    DESCRIPTION = "Load images from subfolders with dynamic filtering. Organize your images in subfolders and select them easily."
    
    def load_image(self, subfolder: str = "", image: str = "", load_mask: bool = True, **kwargs) -> Tuple:
        """
        Load image from the specified subfolder.
        
        Args:
            subfolder: Selected subfolder name
            image: Image filename or path (may contain subfolder prefix)
            load_mask: Whether to extract alpha channel as mask
            
        Returns:
            Tuple of (image_tensor, mask_tensor, filename, width, height)
        """
        try:
            if not image:
                raise ValueError("No image specified")
            
            input_dir = folder_paths.get_input_directory()
            
            # The image parameter now contains the full path (subfolder/filename) when applicable
            # Use it directly as the image identifier for ComfyUI
            image_identifier = image
            
            # Extract clean filename for return value
            if '/' in image:
                parts = image.split('/')
                clean_image = parts[-1]  # Get the filename part
            else:
                clean_image = image
            
            # Use ComfyUI's standard method to get the full file path
            # This handles the path resolution and validation automatically
            file_path = folder_paths.get_annotated_filepath(image_identifier)
            
            # Load and process image
            image_tensor, mask_tensor = self.process_image(file_path, load_mask)
            
            # Get image dimensions
            height, width = image_tensor.shape[1:3]
            
            # Return just the clean filename, not the full path
            return (image_tensor, mask_tensor, clean_image, width, height)
            
        except Exception as e:
            logging.error(f"Error loading image '{image}' from subfolder '{subfolder}': {str(e)}")
            # Return empty tensors on error
            empty_image = torch.zeros((1, 512, 512, 3), dtype=torch.float32)
            empty_mask = torch.zeros((1, 512, 512), dtype=torch.float32)
            return (empty_image, empty_mask, "error", 512, 512)
    
    def process_image(self, file_path: str, load_mask: bool = True) -> Tuple[torch.Tensor, torch.Tensor]:
        """Process image file into tensors."""
        with Image.open(file_path) as img:
            # Store original mode
            original_mode = img.mode
            mask_array = None
            
            # Handle different image modes
            if img.mode == 'RGBA' and load_mask:
                # Extract alpha channel as mask before conversion
                mask_array = np.array(img.getchannel('A'))
                img = img.convert('RGB')
            elif img.mode == 'P':
                # Convert palette images
                if 'transparency' in img.info:
                    img = img.convert('RGBA')
                    if load_mask:
                        mask_array = np.array(img.getchannel('A'))
                    img = img.convert('RGB')
                else:
                    img = img.convert('RGB')
            elif img.mode == 'L':
                # Convert grayscale to RGB
                img = img.convert('RGB')
            elif img.mode not in ['RGB']:
                # Convert any other mode to RGB
                img = img.convert('RGB')
            
            # Convert to numpy array
            image_array = np.array(img, dtype=np.float32) / 255.0
            
            # Ensure we have 3 channels
            if len(image_array.shape) == 2:
                image_array = np.stack([image_array] * 3, axis=-1)
            
            # Convert to tensor
            image_tensor = torch.from_numpy(image_array)
            
            # Add batch dimension
            image_tensor = image_tensor.unsqueeze(0)
            
            # Create mask tensor
            if load_mask and mask_array is not None:
                mask_tensor = torch.from_numpy(mask_array.astype(np.float32) / 255.0)
                mask_tensor = mask_tensor.unsqueeze(0)
            else:
                # Create default mask (all opaque)
                h, w = image_tensor.shape[1:3]
                mask_tensor = torch.ones((1, h, w), dtype=torch.float32)
            
            return image_tensor, mask_tensor
