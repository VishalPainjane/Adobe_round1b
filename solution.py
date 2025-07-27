import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
import json
import time
import os
import argparse
import re
import torch
from collections import defaultdict, OrderedDict

# --- Constants ---
RETRIEVER_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
REASONING_MODEL = 't5-small'

# --- Fixed Paths Inside the Container ---
# These paths correspond to the volumes mounted in the 'docker run' command.
INPUT_DIR = "/app/input"
OUTPUT_DIR = "/app/output"
PDF_SUBDIR = "PDFs"
INPUT_JSON_NAME = "challenge1b_input.json"
OUTPUT_JSON_NAME = "challenge1b_output.json"


# --- Helper Functions ---

def parse_and_chunk_with_page_accuracy(doc, doc_filename, chunk_size=150, overlap=30):
    """
    Parses a PDF. It heuristically finds the main title from the first page
    to use as the default section title for any content not under a sub-header.
    """
    # --- Step 1: Find the Main Title of the Document ---
    main_title = ""
    if len(doc) > 0:
        first_page = doc[0]
        max_font_size = 0
        blocks = first_page.get_text("dict", sort=True)["blocks"]
        
        for block in blocks:
            if "lines" in block and block.get("lines"):
                for line in block["lines"]:
                    if "spans" in line and line.get("spans"):
                        for span in line["spans"]:
                            if span["size"] > max_font_size:
                                max_font_size = span["size"]
        
        if max_font_size > 0:
            potential_titles = []
            for block in blocks:
                if "lines" in block and block.get("lines") and block["lines"][0].get("spans"):
                    if abs(block["lines"][0]["spans"][0]["size"] - max_font_size) < 1:
                        text = " ".join("".join(s["text"] for s in l["spans"]) for l in block["lines"]).strip()
                        if 1 < len(text.split()) < 20:
                            potential_titles.append({"text": text, "y0": block["bbox"][1]})
            
            if potential_titles:
                potential_titles.sort(key=lambda x: x['y0'])
                main_title = potential_titles[0]['text']

    fallback_title = main_title if main_title else os.path.splitext(doc_filename)[0]

    # --- Step 2: Find all other Sub-Headers ---
    headers = []
    for page_num, page in enumerate(doc, 1):
        blocks = page.get_text("dict", sort=True)["blocks"]
        for block in blocks:
            if block.get("lines") and len(block["lines"]) == 1 and block["lines"][0].get("spans"):
                span = block["lines"][0]["spans"][0]
                text = "".join([s["text"] for s in block["lines"][0]["spans"]]).strip()
                if text == main_title:
                    continue
                if (span["size"] > 13 and "bold" in span["font"].lower()) or span["size"] > 16:
                    if 1 < len(text.split()) < 15 and not text.endswith('.'):
                        headers.append({"title": text, "page": page_num, "y0": block["bbox"][1]})
    headers.sort(key=lambda x: (x['page'], x['y0']))

    # --- Step 3: Group text under the correct headers and chunk ---
    chunks = []
    last_header_from_prev_page = fallback_title 
    
    for page_num, page in enumerate(doc, 1):
        headers_on_page = [h for h in headers if h['page'] == page_num]
        content_by_section = defaultdict(str)
        current_header_on_page = last_header_from_prev_page
        header_on_page_idx = 0
        
        blocks = page.get_text("dict", sort=True)["blocks"]
        for block in blocks:
            if not block.get("lines"):
                continue

            block_y0 = block["bbox"][1]
            block_text = " ".join("".join(s['text'] for s in l['spans']) for l in block['lines']).strip()

            is_a_header = (block_text == main_title or any(h['title'] == block_text for h in headers_on_page))
            if is_a_header:
                continue

            if header_on_page_idx < len(headers_on_page) and block_y0 >= headers_on_page[header_on_page_idx]['y0']:
                current_header_on_page = headers_on_page[header_on_page_idx]['title']
                header_on_page_idx += 1
            
            if block_text:
                content_by_section[current_header_on_page] += block_text + " "

        for header, content in content_by_section.items():
            content = re.sub(r'\s+', ' ', content).strip()
            tokens = content.split()
            
            for i in range(0, len(tokens), chunk_size - overlap):
                chunk_text = " ".join(tokens[i:i + chunk_size])
                if len(chunk_text.split()) > 20:
                    chunks.append({
                        "document": doc_filename,
                        "page_num": page_num,
                        "parent_section_title": header,
                        "content": chunk_text
                    })
        
        if headers_on_page:
            last_header_from_prev_page = headers_on_page[-1]['title']
        else:
            last_header_from_prev_page = current_header_on_page
            
    return chunks

# --- Main Processing Logic ---

def process_documents(retriever, reasoner):
    start_time = time.time()
    
    input_json_path = os.path.join(INPUT_DIR, INPUT_JSON_NAME)
    pdfs_path = os.path.join(INPUT_DIR, PDF_SUBDIR)
    
    # The output directory is the root of the mounted output volume.
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_json_path = os.path.join(OUTPUT_DIR, OUTPUT_JSON_NAME)

    with open(input_json_path, 'r') as f:
        input_data = json.load(f)

    persona = input_data["persona"]["role"]
    job_to_be_done = input_data["job_to_be_done"]["task"]
    
    print(f"Processing documents from: {INPUT_DIR}")
    all_chunks = []
    for doc_info in input_data["documents"]:
        doc_filename = doc_info["filename"]
        doc_path = os.path.join(pdfs_path, doc_filename)
        if os.path.exists(doc_path):
            print(f"Parsing {doc_filename}...")
            doc = fitz.open(doc_path)
            all_chunks.extend(parse_and_chunk_with_page_accuracy(doc, doc_filename))

    if not all_chunks:
        print("Could not parse any valid chunks.")
        return

    # Step 1: Reason
    print("Reasoning about user intent...")
    expansion_prompt = f"Based on the request from a '{persona}' to '{job_to_be_done}', generate a list of 4 distinct search queries to find the most useful information. Output only a newline-separated list."
    expanded_queries_text = reasoner(expansion_prompt, max_length=128, num_return_sequences=1)[0]['generated_text']
    cleaned_text = re.sub(r'^\s*[\d\.\-]+\s*', '', expanded_queries_text, flags=re.MULTILINE)
    expanded_queries = [q.strip() for q in cleaned_text.split('\n') if q.strip()]
    if not expanded_queries: expanded_queries = [job_to_be_done]
    print(f"Generated queries: {expanded_queries}")

    # Step 2: Retrieve
    print(f"Retrieving relevant chunks for {len(expanded_queries)} queries...")
    chunk_contents = [chunk['content'] for chunk in all_chunks]
    chunk_embeddings = retriever.encode(chunk_contents, show_progress_bar=True)
    query_embeddings = retriever.encode(expanded_queries)
    
    scores = torch.tensor(chunk_embeddings) @ torch.tensor(query_embeddings).T
    final_scores = torch.max(scores, dim=1).values
    
    for i, chunk in enumerate(all_chunks):
        chunk['score'] = final_scores[i].item()
        
    ranked_chunks = sorted(all_chunks, key=lambda x: x['score'], reverse=True)

    # --- Step 3 & 4: Refine and Generate Output ---
    print("Finding top sections from best chunks...")
    top_sections = OrderedDict()
    for chunk in ranked_chunks:
        if len(top_sections) >= 5:
            break
        section_id = (chunk['document'], chunk['parent_section_title'])
        if section_id not in top_sections:
            top_sections[section_id] = chunk

    output = { "metadata": { "input_documents": [d["filename"] for d in input_data["documents"]], "persona": persona, "job_to_be_done": job_to_be_done, "processing_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) }, "extracted_sections": [], "subsection_analysis": [] }

    for i, (section_id, best_chunk) in enumerate(top_sections.items()):
        doc_filename, section_title = section_id
        
        output["extracted_sections"].append({
            "document": doc_filename,
            "section_title": section_title,
            "importance_rank": i + 1,
            "page_number": best_chunk['page_num'] 
        })
        
        output["subsection_analysis"].append({
            "document": doc_filename,
            "refined_text": best_chunk['content'],
            "page_number": best_chunk['page_num']
        })

    with open(output_json_path, 'w') as f:
        json.dump(output, f, indent=4)

    print(f"Processing complete. Output written to {output_json_path}")
    print(f"Total processing time: {time.time() - start_time:.2f} seconds")


if __name__ == '__main__':
    # Argument parsing is no longer needed as paths are fixed.
    if not os.path.isdir(INPUT_DIR):
        print(f"Error: Input directory not found at {INPUT_DIR}")
        print("Please ensure you have correctly mounted a volume to this location using '-v'.")
        exit(1)

    print("Loading AI models from cache...")

    # --- FIX ---
    # Force SentenceTransformer to load from local cache only.
    retriever_model = SentenceTransformer(RETRIEVER_MODEL, local_files_only=True)

    # Force the transformers pipeline to load from local cache only by loading
    # the tokenizer and model components separately first. This is more robust.
    tokenizer = AutoTokenizer.from_pretrained(REASONING_MODEL, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(REASONING_MODEL, local_files_only=True)
    reasoner_pipeline = pipeline('text2text-generation', model=model, tokenizer=tokenizer, device=-1)
    
    process_documents(retriever_model, reasoner_pipeline)
