import os
import base64
import subprocess
import logging

logger = logging.getLogger(__name__)

def encode_image_audio_video(media_path: str) -> str:
    """
    Smart media encoding: checks size and auto-compresses if needed.
    Returns base64 encoded string.
    """
    # API limits Base64 data size to 10MB
    # Base64 encoded size is approx 4/3 of original file
    # So safe file size limit is approx 10MB / 1.333 = 7.5MB
    MAX_FILE_SIZE_MB = 7.5
    
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"File not found: {media_path}")

    file_size_mb = os.path.getsize(media_path) / (1024 * 1024)
    
    if file_size_mb <= MAX_FILE_SIZE_MB:
        logger.info(f"File size {file_size_mb:.2f}MB is within limit. Encoding directly.")
        with open(media_path, "rb") as media_file:
            return base64.b64encode(media_file.read()).decode("utf-8")
            
    logger.info(f"File size {file_size_mb:.2f}MB exceeds limit ({MAX_FILE_SIZE_MB}MB). Compressing...")
    
    filename, ext = os.path.splitext(media_path)
    ext = ext.lower()
    output_path = f"{filename}_compressed{ext}"
    
    # Check if cached compressed file exists
    if os.path.exists(output_path):
        logger.info(f"Found cached compressed file: {output_path}")
        try:
            with open(output_path, "rb") as media_file:
                return base64.b64encode(media_file.read()).decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to read cached file {output_path}: {e}. Re-compressing.")

    try:
        # Compress based on file type
        if ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
            # Get video duration
            cmd_dur = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", media_path
            ]
            try:
                duration = float(subprocess.check_output(cmd_dur).decode().strip())
            except:
                duration = 60 # Default 60s if failed
                logger.warning("Failed to get video duration, defaulting to 60s")

            # Calculate target bitrate
            # Target size (bits) = 7.5MB * 8 * 1024 * 1024
            # Total bitrate = Target size / duration
            target_total_bitrate = (MAX_FILE_SIZE_MB * 8 * 1024 * 1024) / duration
            # Video 85%, Audio 15% (or fixed audio 64k)
            video_bitrate = int(target_total_bitrate) - 64000
            
            # Limit min bitrate to avoid too poor quality
            video_bitrate = max(video_bitrate, 100000) # Min 100kbps
            
            logger.info(f"Compressing video with target bitrate: {video_bitrate/1000:.0f}k")
            
            cmd = [
                "ffmpeg", "-i", media_path,
                "-b:v", str(video_bitrate),
                "-b:a", "64k",
                "-y", output_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        elif ext in ['.jpg', '.jpeg', '.png', '.bmp', '.webp']:
            # Scale image down by half
            cmd = ["ffmpeg", "-i", media_path, "-vf", "scale=iw/2:ih/2", "-y", output_path]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        elif ext in ['.mp3', '.wav', '.aac', '.flac', '.m4a', '.ogg']:
             # Reduce audio bitrate
            cmd = ["ffmpeg", "-i", media_path, "-b:a", "32k", "-y", output_path]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        else:
            logger.warning(f"Unsupported format {ext} for auto-compression. Trying original.")
            with open(media_path, "rb") as media_file:
                return base64.b64encode(media_file.read()).decode("utf-8")

        # Check if compressed file satisfies requirement
        new_size = os.path.getsize(output_path) / (1024 * 1024)
        logger.info(f"Compressed size: {new_size:.2f}MB")
        
        with open(output_path, "rb") as media_file:
            return base64.b64encode(media_file.read()).decode("utf-8")
            
    except Exception as e:
        logger.error(f"Compression failed: {e}. Using original file.")
        with open(media_path, "rb") as media_file:
            return base64.b64encode(media_file.read()).decode("utf-8")
