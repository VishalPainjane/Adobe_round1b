# # Use a slim Python base image
# FROM python:3.9-slim

# # Set environment variables to control model caching paths
# ENV TRANSFORMERS_CACHE=/models/hf_cache
# ENV SENTENCE_TRANSFORMERS_HOME=/models/sentence_cache

# # Create cache directories
# RUN mkdir -p /models/hf_cache /models/sentence_cache

# WORKDIR /round2

# # Install basic dependencies
# RUN apt-get update && apt-get install -y \
#     git \
#     curl \
#     && rm -rf /var/lib/apt/lists/*

# # Copy requirements first
# COPY requirements.txt .

# # Install PyTorch (CPU)
# RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# # Install other dependencies
# RUN pip install --no-cache-dir -r requirements.txt

# # --- Pre-download models into the defined cache locations ---
# RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
# RUN python -c "from transformers import pipeline; pipeline('text2text-generation', model='t5-small')"


# # Copy project code
# COPY . .

# # Set entrypoint
# # ENTRYPOINT ["python", "solution.py", "--collection"]
# ENTRYPOINT ["python", "solution.py"]




# Use a slim Python base image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Set environment variables for Hugging Face to use a specific cache directory
# This ensures the models are saved within the image layers.
ENV HF_HOME=/app/huggingface_cache
ENV SENTENCE_TRANSFORMERS_HOME=/app/huggingface_cache/hub

# Copy the requirements file into the container
COPY requirements.txt .

# Install the Python dependencies. This step requires internet.
# The --no-cache-dir flag is used to keep the image size smaller.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the model downloader script into the container
COPY download_models.py .

# Run the script to download and cache the models. This step also requires internet.
# The models will be stored in the directory defined by HF_HOME.
RUN python download_models.py

# Copy your main application script into the container
COPY solution.py .

# Set the entrypoint for the container. This command will be executed when the container starts.
# The arguments to the script (like --collection) will be appended when you run 'docker run'.
ENTRYPOINT ["python", "solution.py"]




