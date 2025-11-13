# Migration from Assistants API to Responses API: Experience & Lessons Learned

## Overview

This document details our experience migrating from OpenAI's **Assistants API** (deprecated) to the **Responses API** (new). It covers the hardships we encountered, how we overcame them, and the limitations we discovered along the way.

## Table of Contents

1. [Key Differences Between APIs](#key-differences-between-apis)
2. [Major Hardships & Solutions](#major-hardships--solutions)
3. [API Limitations & Workarounds](#api-limitations--workarounds)
4. [File Handling Challenges](#file-handling-challenges)
5. [Image Extraction & Display](#image-extraction--display)
6. [Code Examples](#code-examples)
7. [Lessons Learned](#lessons-learned)

---

## Key Differences Between APIs

### 1. **Architecture Changes**

| Assistants API | Responses API |
|----------------|---------------|
| `assistants` → `threads` → `runs` | `responses` (unified) |
| Separate objects for each concept | Single response object |
| State managed via threads | State managed via conversations |
| `assistant_id` + `thread_id` + `run_id` | `response_id` + `conversation_id` |

### 2. **Terminology Mapping**

```python
# Old (Assistants API)
assistant_id = "asst_xxx"
thread_id = "thread_xxx"
run_id = "run_xxx"

# New (Responses API)
response_id = "resp_xxx"  # Configuration ID
conversation_id = "conv_xxx"  # Conversation state
```

### 3. **Message Format Changes**

**Assistants API:**
```python
# Messages were added to threads
client.threads.messages.create(
    thread_id=thread_id,
    role="user",
    content="Hello"
)
```

**Responses API:**
```python
# Messages are passed in the input parameter
client.responses.create(
    input=[
        {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}
    ]
)
```

### 4. **Content Type Changes**

**Assistants API:**
- Text content was a simple string
- Files were attached via `file_ids` parameter

**Responses API:**
- Text content must use `{"type": "input_text", "text": "..."}`
- Files must use `{"type": "input_file", "file_id": "..."}` in content array
- **Critical**: Content must be an array, not a string

---

## Major Hardships & Solutions

### Hardship 1: Content Format Mismatch

**Problem:**
```python
# This failed with error:
# "Invalid value: 'text'. Supported values are: 'input_text', 'input_image', ..."
{
    "role": "user",
    "content": [{"type": "text", "text": "Hello"}]  # ❌ Wrong type
}
```

**Solution:**
```python
# Correct format:
{
    "role": "user",
    "content": [{"type": "input_text", "text": "Hello"}]  # ✅ Correct
}
```

**Location:** `app/openai_client.py:519`

---

### Hardship 2: File Attachments Parameter Removed

**Problem:**
```python
# This failed with error:
# "Unknown parameter: 'input[0].attachments'"
{
    "role": "user",
    "content": "Hello",
    "attachments": [{"file_id": "file-xxx"}]  # ❌ Not supported
}
```

**Solution:**
```python
# Files must be in the content array:
{
    "role": "user",
    "content": [
        {"type": "input_text", "text": "Hello"},
        {"type": "input_file", "file_id": "file-xxx"}  # ✅ Correct
    ]
}
```

**Location:** `app/openai_client.py:512-535`

**Implementation Details:**
- We store file IDs internally as `_file_ids` in message objects
- When building API requests, we convert them to the content array format
- Different handling for `file_search` (PDFs) vs `code_interpreter` (CSVs)

---

### Hardship 3: File Search Only Accepts PDFs

**Problem:**
```python
# This failed when trying to use CSV with file_search:
# "Invalid input: Expected context stuffing file type to be a supported format: .pdf but got .csv"
{
    "type": "input_file",
    "file_id": "file-xxx"  # CSV file
}
# When file_search tool is enabled
```

**Root Cause:**
- `file_search` tool (for knowledge base retrieval) only accepts PDF files
- CSV files cannot be used with `file_search`
- CSV files must be used with `code_interpreter` tool instead

**Solution:**
```python
# For file_search (PDFs only):
if has_file_search and not has_code_interpreter:
    content_parts.append({
        "type": "input_file",
        "file_id": file_id  # Only PDFs
    })

# For code_interpreter (CSVs, images, etc.):
# Files are mounted in the container, NOT in input_file
if has_code_interpreter and file_ids:
    tools = [{
        "type": "code_interpreter",
        "container": {
            "type": "auto",
            "file_ids": file_ids  # CSV files go here
        }
    }]
```

**Location:** `app/openai_client.py:522-585`

**Key Insight:**
- **PDFs** → Use `input_file` in content array (for `file_search`)
- **CSVs** → Use `container.file_ids` in tool config (for `code_interpreter`)
- Never mix them in the same request

---

### Hardship 4: Code Interpreter Files Must Be in Container Config

**Problem:**
```python
# This failed - CSV files were rejected when passed as input_file
# Even when code_interpreter was enabled
{
    "content": [
        {"type": "input_text", "text": "Analyze this CSV"},
        {"type": "input_file", "file_id": "file-csv-xxx"}  # ❌ Wrong for CSV
    ],
    "tools": [{"type": "code_interpreter"}]
}
```

**Solution:**
```python
# CSV files must be in the container configuration:
{
    "content": [
        {"type": "input_text", "text": "Analyze this CSV"}
        # No input_file for CSV!
    ],
    "tools": [{
        "type": "code_interpreter",
        "container": {
            "type": "auto",
            "file_ids": ["file-csv-xxx"]  # ✅ CSV files here
        }
    }]
}
```

**Location:** `app/openai_client.py:560-585`

---

### Hardship 5: Image Extraction from Container Files

**Problem:**
- When `code_interpreter` generates images (e.g., charts from CSV data), the images are stored in **container files**
- Container files have IDs like `cfile_xxx` (not `file_xxx`)
- The Python SDK doesn't fully support downloading container files
- Images were not appearing in the UI

**Initial Attempt:**
```python
# This failed - SDK doesn't support container files
file_response = client.containers.files.content(container_id, file_id)
# TypeError: 'Content' object is not callable
```

**Solution:**
```python
# Use direct HTTP requests to download container files
def download_container_file_bytes(container_id: str, file_id: str) -> bytes:
    """Download container file via direct HTTP request."""
    url = f"{base_url}/containers/{container_id}/files/{file_id}/content"
    
    req = Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    if org_id:
        req.add_header("OpenAI-Organization", org_id)
    if project_id:
        req.add_header("OpenAI-Project", project_id)
    
    response = urlopen(req, timeout=60.0)
    return response.read()
```

**Location:** `app/openai_client.py:1889-1927`

**Additional Challenge:**
- Container file IDs are found in `container_file_citation` annotations
- These annotations appear in `output_text` content items
- We had to extract `file_id` and `container_id` from these annotations

**Location:** `app/openai_client.py:1239-1267`

---

### Hardship 6: Image Display Architecture

**Problem:**
- Initially, we downloaded images and converted them to base64 data URLs
- This blocked the API response and was inefficient for large images
- API requests would hang if image downloads failed

**Initial Approach:**
```python
# ❌ Blocking approach
image_bytes = download_container_file_bytes(container_id, file_id)
base64_data = base64.b64encode(image_bytes).decode("utf-8")
data_url = f"data:image/png;base64,{base64_data}"
return {"images": [{"data_url": data_url}]}
```

**Solution:**
```python
# ✅ On-demand serving approach
# Return image URLs instead of base64 data
return {
    "images": [{
        "file_id": file_id,
        "container_id": container_id,
        "url": f"/api/container-file/{container_id}/{file_id}"
    }]
}

# Frontend fetches images on-demand
<img src="/api/container-file/{container_id}/{file_id}" />
```

**Benefits:**
- Non-blocking API responses
- Lazy loading of images
- Better error handling (failed downloads don't crash the request)
- More efficient for large images

**Location:** 
- Backend: `app/main.py:663-674` (API endpoints)
- Backend: `app/openai_client.py:2237-2252` (URL generation)
- Frontend: `app/static/index.html:625-631` (image rendering)

---

### Hardship 7: Response Structure Changes

**Problem:**
- Assistants API returned text in `message.content[].text.value`
- Responses API returns text directly in `content_item["text"]` (string, not nested object)

**Initial Code:**
```python
# ❌ This didn't work
text = content_item.text.value  # AttributeError
```

**Solution:**
```python
# ✅ Correct extraction
if isinstance(content_item, dict):
    text_value = content_item.get("text", "")  # Direct string
elif hasattr(content_item, "text"):
    text_attr = content_item.text
    if isinstance(text_attr, str):
        text_value = text_attr  # Already a string
```

**Location:** `app/openai_client.py:1312-1347`

---

### Hardship 8: Citation Extraction

**Problem:**
- Citations appear in `annotations` array within `output_text` content
- Structure is different from Assistants API
- Need to handle both `file_citation` and `container_file_citation`

**Solution:**
```python
# Extract from annotations
annotations = content_item.get("annotations", [])
for ann in annotations:
    ann_type = ann.get("type")
    
    if ann_type == "file_citation":
        # Regular file citation (for file_search)
        file_id = ann.get("file_citation", {}).get("file_id")
        quote = ann.get("file_citation", {}).get("quote", "")
    
    elif ann_type == "container_file_citation":
        # Container file citation (for code_interpreter images)
        file_id = ann.get("file_id")
        container_id = ann.get("container_id")
        filename = ann.get("filename")
        
        # Check if it's an image
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            images.append({"file_id": file_id, "container_id": container_id})
```

**Location:** `app/openai_client.py:1349-1436`

---

## API Limitations & Workarounds

### Limitation 1: File Search Only Accepts PDFs

**Limitation:**
- `file_search` tool only accepts PDF files
- Cannot use CSV, images, or other file types with `file_search`

**Workaround:**
- Use `code_interpreter` for CSV files
- Pass CSV files in `container.file_ids` instead of `input_file`
- Keep PDFs for knowledge base retrieval, CSVs for data analysis

**Code:**
```python
# Detect file type and route accordingly
if filename.endswith('.pdf'):
    # Use file_search
    content_parts.append({"type": "input_file", "file_id": file_id})
    tools = [{"type": "file_search", "vector_store_ids": [vs_id]}]
elif filename.endswith('.csv'):
    # Use code_interpreter
    tools = [{
        "type": "code_interpreter",
        "container": {"type": "auto", "file_ids": [file_id]}
    }]
```

---

### Limitation 2: Container Files Not Fully Supported in SDK

**Limitation:**
- Python SDK doesn't have full support for downloading container files
- `client.containers.files.content()` doesn't work as expected

**Workaround:**
- Use direct HTTP requests to `/v1/containers/{container_id}/files/{file_id}/content`
- Use `urllib` from standard library (no external dependencies)
- Handle errors gracefully to prevent API hanging

**Code:**
```python
from urllib.request import Request, urlopen

url = f"{base_url}/containers/{container_id}/files/{file_id}/content"
req = Request(url)
req.add_header("Authorization", f"Bearer {api_key}")
response = urlopen(req, timeout=60.0)
return response.read()
```

---

### Limitation 3: No Direct Container File Listing

**Limitation:**
- No API endpoint to list files in a container
- Must extract file IDs from response annotations

**Workaround:**
- Parse `container_file_citation` annotations in response output
- Extract `file_id` and `container_id` from annotations
- Check filename extension to identify images

---

### Limitation 4: Content Must Be Array Format

**Limitation:**
- Responses API requires content to be an array, even for simple text
- Cannot use string format like Assistants API

**Workaround:**
- Always convert content to array format
- Use `{"type": "input_text", "text": "..."}` for text
- Use `{"type": "input_file", "file_id": "..."}` for files

---

## File Handling Challenges

### Challenge 1: Different File Types, Different Handling

**PDF Files (Knowledge Base):**
```python
# For file_search tool
{
    "content": [
        {"type": "input_text", "text": "Search the knowledge base"},
        {"type": "input_file", "file_id": "file-pdf-xxx"}
    ],
    "tools": [{"type": "file_search", "vector_store_ids": [vs_id]}]
}
```

**CSV Files (Data Analysis):**
```python
# For code_interpreter tool
{
    "content": [
        {"type": "input_text", "text": "Analyze this data"}
        # NO input_file for CSV!
    ],
    "tools": [{
        "type": "code_interpreter",
        "container": {
            "type": "auto",
            "file_ids": ["file-csv-xxx"]  # CSV in container
        }
    }]
}
```

**Key Rule:**
- **Never** use `input_file` for CSV files when `code_interpreter` is enabled
- **Always** put CSV files in `container.file_ids`
- **Only** use `input_file` for PDFs with `file_search`

---

### Challenge 2: Mixed Tools Scenario

**Problem:**
- What if both `file_search` and `code_interpreter` are enabled?
- How to handle PDFs and CSVs in the same request?

**Solution:**
```python
# PDFs go in input_file (for file_search)
# CSVs go in container.file_ids (for code_interpreter)

content_parts = [
    {"type": "input_text", "text": user_message}
]

# Add PDFs to content
for file_id in pdf_file_ids:
    content_parts.append({"type": "input_file", "file_id": file_id})

# Add CSVs to container
tools = [
    {"type": "file_search", "vector_store_ids": [vs_id]},
    {
        "type": "code_interpreter",
        "container": {
            "type": "auto",
            "file_ids": csv_file_ids  # CSVs here
        }
    }
]
```

---

## Image Extraction & Display

### Image Extraction Flow

1. **Response contains `output_text` with annotations**
2. **Annotations include `container_file_citation`**
3. **Extract `file_id` and `container_id` from annotation**
4. **Check filename extension to identify images**
5. **Store image metadata (file_id, container_id)**

**Code:**
```python
# In _extract_text_and_citations_from_response()
for ann in annotations:
    if ann.get("type") == "container_file_citation":
        file_id = ann.get("file_id")
        container_id = ann.get("container_id")
        filename = ann.get("filename")
        
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            images.append({
                "file_id": file_id,
                "container_id": container_id
            })
```

### Image Serving Architecture

**Backend API Endpoints:**
```python
@app.get("/api/container-file/{container_id}/{file_id}")
def get_container_file(container_id: str, file_id: str):
    """Download and serve container file (image)."""
    data = download_container_file_bytes(container_id, file_id)
    return Response(content=data, media_type="image/png")
```

**Frontend Display:**
```javascript
// Images are served on-demand via API endpoints
structuredData.images.forEach((image) => {
    if (image.url) {
        html += `<img src="${image.url}" />`;
    }
});
```

**Benefits:**
- Non-blocking responses
- Lazy loading
- Better error handling
- Efficient for large images

---

## Code Examples

### Example 1: Complete File Handling

```python
def run_response(conversation_id, response_config_id, file_ids=None):
    # Determine which tools are enabled
    config = get_response_config(response_config_id)
    tools = config.get("tools", [])
    
    has_file_search = any(t.get("type") == "file_search" for t in tools)
    has_code_interpreter = any(t.get("type") == "code_interpreter" for t in tools)
    
    # Separate PDFs from CSVs
    pdf_files = []
    csv_files = []
    for file_id in file_ids:
        file_info = client.files.retrieve(file_id)
        if file_info.filename.endswith('.pdf'):
            pdf_files.append(file_id)
        elif file_info.filename.endswith('.csv'):
            csv_files.append(file_id)
    
    # Build content array
    content_parts = [{"type": "input_text", "text": user_message}]
    
    # Add PDFs to content (for file_search)
    if has_file_search:
        for pdf_id in pdf_files:
            content_parts.append({"type": "input_file", "file_id": pdf_id})
    
    # Add CSVs to container (for code_interpreter)
    if has_code_interpreter and csv_files:
        for tool in tools:
            if tool.get("type") == "code_interpreter":
                tool["container"]["file_ids"] = csv_files
    
    # Create response
    response = client.responses.create(
        input=[{"role": "user", "content": content_parts}],
        tools=tools
    )
```

### Example 2: Image Extraction

```python
def extract_images_from_response(response):
    images = []
    
    for output_item in response.output:
        for content_item in output_item.get("content", []):
            if content_item.get("type") == "output_text":
                annotations = content_item.get("annotations", [])
                
                for ann in annotations:
                    if ann.get("type") == "container_file_citation":
                        file_id = ann.get("file_id")
                        container_id = ann.get("container_id")
                        filename = ann.get("filename")
                        
                        # Check if it's an image
                        if filename and filename.lower().endswith(
                            ('.png', '.jpg', '.jpeg', '.gif', '.webp')
                        ):
                            images.append({
                                "file_id": file_id,
                                "container_id": container_id
                            })
    
    return images
```

### Example 3: Container File Download

```python
def download_container_file_bytes(container_id: str, file_id: str) -> bytes:
    """Download container file via HTTP (SDK doesn't support it)."""
    import os
    from urllib.request import Request, urlopen
    
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    
    url = f"{base_url}/containers/{container_id}/files/{file_id}/content"
    
    req = Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    
    response = urlopen(req, timeout=60.0)
    return response.read()
```

---

## Lessons Learned

### 1. **Always Check Content Types**
- Responses API is strict about content types
- Use `input_text` not `text`
- Use `input_file` not `file`

### 2. **File Type Determines Tool Usage**
- PDFs → `file_search` → `input_file` in content
- CSVs → `code_interpreter` → `container.file_ids` in tool config
- Never mix them incorrectly

### 3. **Container Files Require Direct HTTP**
- SDK doesn't fully support container files
- Use direct HTTP requests for downloading
- Handle errors gracefully

### 4. **Images Are in Annotations**
- Images don't appear as separate content items
- They're in `container_file_citation` annotations
- Must parse annotations to find images

### 5. **On-Demand Serving is Better**
- Don't download images during API response
- Serve them via separate endpoints
- Frontend fetches on-demand

### 6. **Content Must Be Arrays**
- Even simple text must be in array format
- `{"type": "input_text", "text": "..."}` is required
- Cannot use string format

### 7. **Error Handling is Critical**
- Container file downloads can fail
- Don't let failures crash the API
- Log errors and skip problematic images

---

## Migration Checklist

- [x] Update terminology (assistant → response, thread → conversation)
- [x] Fix content format (text → input_text)
- [x] Fix file attachments (attachments → content array)
- [x] Separate PDF and CSV handling
- [x] Implement container file downloads
- [x] Extract images from annotations
- [x] Create image serving endpoints
- [x] Update frontend to use image URLs
- [x] Handle errors gracefully
- [x] Remove debug logging

---

## Conclusion

The migration from Assistants API to Responses API required significant changes to file handling, content formatting, and image extraction. The key challenges were:

1. **File type separation**: PDFs vs CSVs require different handling
2. **Container files**: SDK limitations required direct HTTP requests
3. **Image extraction**: Images are hidden in annotations, not direct content
4. **Content format**: Strict array format requirements

By understanding these differences and implementing appropriate workarounds, we successfully migrated the application while maintaining all functionality.

---

## References

- **Code Locations:**
  - File handling: `app/openai_client.py:500-585`
  - Image extraction: `app/openai_client.py:1239-1267`
  - Container downloads: `app/openai_client.py:1889-1927`
  - API endpoints: `app/main.py:651-674`
  - Frontend: `app/static/index.html:621-631`

- **Related Documentation:**
  - `MIGRATION_GUIDE.md` - General migration guide
  - `MIGRATION_COMPLETE.md` - Migration status
  - `SYSTEM_EXPLANATION.md` - System architecture

