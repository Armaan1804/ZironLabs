import tempfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from freight_parser.agent import process_document
from freight_parser.ingest import load_document_text
from freight_parser.errors import IngestionError, ConfigError
from freight_parser.config import get_config

app = FastAPI(title="Freight Parser API")

# Setup CORS just in case
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/parse")
async def parse_document(file: UploadFile = File(...)):
    """Accepts a file upload, extracts its text, and parses it via LLM."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    
    # Check config early
    try:
        get_config()
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".txt", ".md"):
        raise HTTPException(status_code=400, detail=f"Unsupported extension: {suffix}. Supported: .pdf, .txt, .md")

    # Create a temporary file to parse
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # 1. Ingest
        raw_text = load_document_text(tmp_path)
        # 2. Extract and Validate
        decision = process_document(raw_text)
        
        # FastAPI handles Pydantic model serialization automatically
        return decision.model_dump()
        
    except IngestionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
    finally:
        # Clean up temporary file
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

@app.get("/api/readme")
async def get_readme():
    """Returns the markdown content of README.md."""
    readme_path = Path(__file__).parent.parent.parent / "README.md"
    if not readme_path.exists():
        return {"content": "README not found."}
    with open(readme_path, "r", encoding="utf-8") as f:
        return {"content": f.read()}

# Mount frontend files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("freight_parser.api:app", host="0.0.0.0", port=8000, reload=True)
