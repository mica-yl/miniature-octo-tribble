# app.py
import os
import uuid
import random
import time
import jwt
import datetime
import logging
import base64

# Configure to use uvicorn's logger so logs match Uvicorn's format exactly
logger = logging.getLogger("uvicorn.error")

import fitz  # PyMuPDF
import io
from typing import List
from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, File, Request, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import httpx
import asyncio

from PIL import Image

from loan_expert import ask_loan_expert

from dotenv import load_dotenv

# This looks for a .env file and loads it into the environment
load_dotenv()

getDetectionEndpoint = lambda : os.getenv("DETECTION_ENDPOINT")


# FastMCP Server
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# Disable DNS rebinding protection (Recommended for PaaS like Railway)
# Since Railway's proxy sits in front of your app, this is safe to do.
security_settings = TransportSecuritySettings(
    enable_dns_rebinding_protection=False
)

mcp_server = FastMCP("bank_mcp", transport_security=security_settings)

app = FastAPI(title="SecureBank Tasks API")

# Enable CORS so your HTML frontend on a different port/domain can fetch the token
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
)

# Allow static files
# os.makedirs("uploads", exist_ok=True)
# app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory storage
tasks_db = {}

# TODO Decide a file interface 
# FIXME inconsistent file interface (images vs uploaded files)
class FileStorage:
    def __init__(self):
        self.files = {}

    def save(self, file: UploadFile,safe_name):
        # filename = file.filename
        self.files[safe_name] = file
        return safe_name

    def save_from_PIL(self, image: Image.Image, filename: str):
        """
        Converts a PIL Image object into an in-memory file (BytesIO) and store it in the file storage.
        """
        # 1. Create the empty in-memory file buffer
        buffer = io.BytesIO()
        
        # 2. Save the PIL image into the buffer
        # Note: You MUST specify the format (PNG, JPEG, etc.)
        image.save(buffer, format="PNG")
        
        # 3. Move the 'cursor' back to the beginning of the file
        # If you don't do this, the next function that reads the file 
        # will think the file is empty because the cursor is at the end.
        buffer.seek(0)
    
        buffer.filename = filename
        self.images[filename] = buffer
        return buffer

    def get(self, filename: str):
        file=self.files.get(filename)
        file.seek(0)
        return file

    def delete(self, filename: str):
        del self.files[filename]

file_storage = FileStorage()


@app.get("/uploads/{filename}")
async def get_uploaded_file(filename: str):
    file = file_storage.get(filename)
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return StreamingResponse(file
    , media_type="application/pdf") # FIXME automatic file type





async def extract_images_to_memory(file_obj: io.BytesIO) -> List[io.BytesIO]:
    """
    Takes an in-memory binary stream (PDF), extracts all embedded images, 
    and returns them as a list of in-memory binary streams.
    """
    # 1. Read the uploaded file into bytes
    file_bytes = file_obj.read()
    file_obj.seek(0)
    
    # 2. Open the PDF from the byte stream
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    image_streams = []

    for page_index in range(len(doc)):
        # Get list of images on the current page
        image_list = doc.get_page_images(page_index)
        
        for img_index, img in enumerate(image_list):
            xref = img[0]  # The internal ID of the image
            
            # Extract the image pixmap
            pix = fitz.Pixmap(doc, xref)
            
            # If the image has an alpha channel (transparency), convert to RGB
            # This prevents errors when saving as JPEG or standard PNGs
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)

            # 3. Save the image data into a BytesIO object
            img_buffer = io.BytesIO()
            img_buffer.write(pix.tobytes("png"))  # You can change "png" to "jpg"

            # Reset the pointer to the beginning so the caller can read it
            img_buffer.seek(0)
            
            image_streams.append(img_buffer)
            
            # Free up pixmap memory
            pix = None 

    doc.close()
    return image_streams


@app.get("/images/{filename}")
async def get_uploaded_image(filename: str):
    file = file_storage.get(filename)
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return StreamingResponse(file, media_type="image/png")

async def check_document(file_input,special=False):
    task_id = str(uuid.uuid4())
    figures=[]
    if special and False:
        for fname in ["a_.png", "b_.png"]:
            if os.path.exists(fname):
                with open(fname, "rb") as f:
                    figures.append(io.BytesIO(f.read()))
    else:
        # figures= extract_all_images_from_pdf(file_input)
        figures.extend(await extract_images_to_memory(file_input))
    subtasks = {}
    for i, figure in enumerate(figures):
        sub_id = str(uuid.uuid4())
        safe_name = f"{uuid.uuid4().hex}.png"
        file_storage.save(figure,safe_name)

        subtasks[sub_id] = {
            "id": sub_id,
            "pid": task_id,
            "image_url": f"/images/{safe_name}",
            "thumb_url": f"/images/{safe_name}",
            "file_name": safe_name,
            "status": "pending",
            "description": f"Extracted page image {i+1}"
        }
    return {"task_id": task_id, "subtasks": subtasks}


# Mock check document API
def mock_check_document(file_input):
    task_id = str(uuid.uuid4())
    num_images = random.randint(3, 6)
    
    subtasks = {}
    picsum_ids = [101, 133, 160, 201, 237, 251, 274, 318, 367]
    
    for i in range(num_images):
        sub_id = str(uuid.uuid4())
        picsum_id = picsum_ids[i % len(picsum_ids)]
        
        subtasks[sub_id] = {
            "id": sub_id,
            "image_url": f"https://picsum.photos/id/{picsum_id}/1200/800",
            "thumb_url": f"https://picsum.photos/id/{picsum_id}/360/240",
            "status": "pending",
            "description": f"Extracted page image {i+1}"
        }
    
    return {"task_id": task_id, "subtasks": subtasks}

async def process_image(subtask):
    file= file_storage.get(subtask["file_name"])
    file.seek(0)
    image_base64= base64.b64encode(file.read()).decode('utf-8')
    payload= {
        "id": subtask['id'],
        "pid": subtask['pid'],
       "image_base64": image_base64
    }
    current_task= tasks_db[subtask['pid']]["subtasks"][subtask['id']]
    try:
        # Use an async HTTP client with no timeout (or a very long one) 
        # since Service A blocks until finished.
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                getDetectionEndpoint(), 
                json=payload
            )
            response.raise_for_status()
            
            # 3. Update something with the results when A finishes
            data = response.json()
            current_task['status']= "completed"
            # current_task['result']= data
            # ....'
            # replace file with masked version
            file=io.BytesIO(base64.b64decode(data['mask_b64']))
            file_storage.save(file,subtask["file_name"])
            

            logger.info(f"Task {current_task['id']} finished and updated.")
            
    except Exception as e:
        current_task['status']= "failed"
        current_task['error'] = str(e)
        logger.error(f"Task {current_task['pid']}-{current_task['id']} failed: {e}", exc_info=True)

    

from fastapi import Request

@app.post("/api/v1/doc-tamper-detection")
def mock_detect(data: dict):
    """
    Mock endpoint to simulate a long running, blocking CPU-bound task.
    By using 'def' instead of 'async def', FastAPI will run this in a threadpool
    to prevent blocking the main asyncio event loop.
    """
    start_time = time.time()
    

    id= data.get("id")
    pid= data.get("pid")

    logger.info(f"Received request to process image {id} for task {pid}")

    # Decode the input image
    input_b64 = data.get("image_base64", "")
    image_data = base64.b64decode(input_b64)
    
    # Simulate a true CPU-bound block.
    time.sleep(0.3*60) 
    
    # Re-encode it
    mask_b64 = base64.b64encode(image_data).decode('utf-8')
    
    execution_time = time.time() - start_time
    
    return {
        "mask_b64": mask_b64,
        "score": round(random.uniform(0.7, 0.99), 4),
        "excution_time_sec": execution_time,
        "modification_percentage": f"{round(random.uniform(0, 100), 2)}%"
    }


async def process_document_file(file_obj: io.BytesIO, filename: str):
        
    # Save PDF
    safe_name = f"{uuid.uuid4().hex[:12]}_{filename}"

    # Ensure the buffer has a filename attribute if other parts of the system expect it
    file_obj.filename = safe_name
    file_storage.save(file_obj, safe_name)

    result = await check_document(file_obj,special=filename=="loan_documents.pdf")
    
    task_id = result["task_id"]
    
    tasks_db[task_id] = {
        "id": task_id,
        "filename": safe_name,
        "pdf_url": f"/uploads/{safe_name}",
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "status": "pending",
        "subtasks": result["subtasks"]
    }
    logger.info(f"File {task_id} uploaded successfully")

    # Process subtasks concurrently in the background so the HTTP request completes quickly
    for subtask in result["subtasks"].values():
        asyncio.create_task(process_image(subtask))
        logger.info(f"Task {subtask['id']} submitted and delegated to document check")
    
    return {"task_id": task_id, "message": "Task submitted and delegated to document check"}

@app.post("/api/submit-task")
async def submit_task(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files allowed")
    
    content = await file.read()
    file_obj = io.BytesIO(content)
    
    return await process_document_file(file_obj, file.filename)


class SubmitUrlRequest(BaseModel):
    pdf_url: str

MAX_FILE_SIZE = 10 * 1024 * 1024 # 10MB

@app.post("/api/submit-url")
async def submit_url(request: SubmitUrlRequest):
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("GET", request.pdf_url, follow_redirects=True) as response:
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_FILE_SIZE:
                    raise HTTPException(status_code=400, detail="File too large (max 10MB)")

                file_obj = io.BytesIO()
                downloaded = 0
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    downloaded += len(chunk)
                    if downloaded > MAX_FILE_SIZE:
                        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
                    file_obj.write(chunk)
                
                file_obj.seek(0)
                
                # Try to extract filename from URL, fallback to random
                filename = request.pdf_url.split("/")[-1].split("?")[0]
                if not filename.lower().endswith(".pdf"):
                    filename = f"url_upload_{uuid.uuid4().hex[:8]}.pdf"
                    
                return await process_document_file(file_obj, filename)
        except httpx.RequestError as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")

@app.get("/api/tasks")
async def get_all_tasks():
    return list(tasks_db.values())

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks_db[task_id]

@app.get("/api/tasks/{pid}/{subtask_id}")
async def get_subtask(pid: str, subtask_id: str):
    if pid not in tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = tasks_db[pid]
    if subtask_id not in task.get("subtasks", {}):
        raise HTTPException(status_code=404, detail="Subtask not found")
        
    return task["subtasks"][subtask_id]

@app.get("/portal/document-compliance")
async def serve_portal1():
    return FileResponse("tasks-portal.html")

@app.get("/portal/document-submission")
async def serve_portal2():
    return FileResponse("submit-document.html")

# --- MCP Tool Registration ---
@mcp_server.tool(name="Loan_Data_Expert")
def loan_data_expert_tool(question: str) -> str:
    """Consult the Loan Data Expert to answer questions about bank mortgages, loans, and rates."""
    try:
        return ask_loan_expert(question)
    except Exception as e:
        return f"Error consulting loan expert: {str(e)}"

@mcp_server.tool()
async def submit_pdf_url(pdf_url: str) -> str:
    """Submit a PDF document from a URL for processing into the SecureBank system."""
    try:
        # Re-use our existing submit_url logic via the Request model
        req = SubmitUrlRequest(pdf_url=pdf_url)
        result = await submit_url(req)
        return f"{result['task_id']}"
    except Exception as e:
        return f"Failed to submit PDF: {str(e)}"

# --- Mount FastMCP into FastAPI ---
# FastMCP provides native Starlette apps we can directly mount
# .sse_app() provides the realtime connected SSE endpoints (GET /sse and POST /messages)
app.mount("/mcp", mcp_server.sse_app())

# .streamable_http_app() provides the stateless endpoint format
# app.mount("/mcp/streamable", mcp_server.streamable_http_app())

@app.get("/favicon.ico")
async def serve_favicon():
    return FileResponse("favicon.ico")


@app.get("/mock-bank-page")
async def serve_mock_bank_page():
    # TODO paramterized template with ibm keys as env vars
    return FileResponse("mock-bank.html")

def read_pkey(fp):
    # Load your private key (Generate with openssl: openssl genrsa -out private.key 4096)
    with open(fp, "r") as key_file:
        return key_file.read()

@app.get("/createJWT", response_class=PlainTextResponse)
def create_jwt():
    """Generates and returns the minimalist Watsonx token."""
    
    jwt_content = {
        "sub": "DemoUser123", # Hardcoded anonymous user ID
        "iss": "my-demo-app",# Issuer: Recommended to prevent strict validation rejections


        "context": {
            "wxo_clientID": "3f497f36-1e9d-47e5-b2b6-ca3286de67f7", # Replace with your actual client ID
            "wxo_name": "Demo Admin",
            "wxo_role": "Admin"
        },
        # Expiration time: Current time + 24 hours
        "exp": int(time.time()) + (24 * 3600) 
    }

    PRIVATE_KEY = read_pkey('example-jwtRS256.key')
    # Sign it with RS256 using PyJWT
    token = jwt.encode(jwt_content, PRIVATE_KEY, algorithm="RS256")
    
    return token

# Main
if __name__ == "__main__":
    # # Add some demo tasks on startup
    # if len(tasks_db) == 0:
    #     demo_task_id = str(uuid.uuid4())
    #     tasks_db[demo_task_id] = {
    #         "id": demo_task_id,
    #         "filename": "loan_application_2025.pdf",
    #         "pdf_url": "/uploads/demo.pdf",
    #         "created_at": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
    #         "status": "pending",
    #         "subtasks": [
    #             {
    #                 "id": str(uuid.uuid4()),
    #                 "image_url": "https://picsum.photos/id/101/1200/800",
    #                 "thumb_url": "https://picsum.photos/id/101/360/240",
    #                 "status": "pending",
    #                 "description": "Extracted page image 1"
    #             },
    #             {
    #                 "id": str(uuid.uuid4()),
    #                 "image_url": "https://picsum.photos/id/237/1200/800",
    #                 "thumb_url": "https://picsum.photos/id/237/360/240",
    #                 "status": "pending",
    #                 "description": "Extracted page image 2"
    #             }
    #         ]
    #     }
    
    uvicorn.run("app:app", host="0.0.0.0", port=8081, reload=True)