import os
import json
from typing import Optional, List, Dict, Any

# Third-party imports
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

# SQLAlchemy 2.0+ imports
from sqlalchemy import create_engine, String, Integer, select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import select

# External HTTP Client
import httpx

# --- 1. Environment Simulation (Replacing .env file) ---
# In a real setup, load from os.environ or dotenv.load_dotenv()
# NOTE: For this code to run successfully, you must install: 
# fastapi uvicorn sqlalchemy pydantic httpx aiosqlite
HUNTER_API_KEY = os.environ.get("HUNTER_IO_API_KEY", "MOCK_KEY_IF_NOT_SET")
DATABASE_URL = "sqlite+aiosqlite:///./contacts.db"


# --- 2. Database Setup ---

class Base(DeclarativeBase):
    pass

# Async Engine Setup
try:
    engine = create_async_engine(DATABASE_URL, echo=False)
except ImportError:
    # Fallback/Warning if aiosqlite isn't installed
    print("Warning: aiosqlite not found. Async DB operations might fail if not installed.")
    # Attempting to use standard sqlite driver if aiosqlite fails initialization, though async features rely on aiosqlite
    engine = create_async_engine(DATABASE_URL.replace("aiosqlite", "sqlite"), echo=False)


AsyncSessionLocal = sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

async def get_db() -> AsyncSession:
    """Dependency to provide an asynchronous database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# --- 3. Model Definition (models.py) ---

class Contact(Base):
    __tablename__ = "contacts"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    hunter_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

# --- 4. Pydantic Schemas (schemas.py) ---

class ContactCreate(BaseModel):
    first_name: str = Field(..., min_length=2)
    last_name: str = Field(..., min_length=2)
    email: EmailStr
    phone: Optional[str] = None

class ContactUpdate(BaseModel):
    # All fields are optional for PATCH/PUT updates
    first_name: Optional[str] = Field(None, min_length=2)
    last_name: Optional[str] = Field(None, min_length=2)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

class ContactResponse(ContactCreate):
    id: int
    hunter_score: Optional[int] = None

    # Pydantic configuration to allow ORM mapping (SQLAlchemy objects)
    class Config:
        from_attributes = True


# --- 5. Hunter.io Integration Service ---

async def verify_email_hunter(email: EmailStr) -> Dict[str, Any]:
    """
    Calls Hunter.io API or returns a mock score if the key is missing or request fails.
    """
    if not HUNTER_API_KEY or HUNTER_API_KEY == "MOCK_KEY_IF_NOT_SET":
        # print(f"Hunter API Key missing. Returning mock score for {email}.")
        return {"score": 50, "status": "mocked_key"}

    hunter_url = f"https://api.hunter.io/v2/email-verifier?email={email}&api_key={HUNTER_API_KEY}"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(hunter_url)
            response.raise_for_status()
            
            data = response.json()
            
            score = data['data'].get('score', 50)
            return {"score": score, "status": "verified"}

    except httpx.HTTPStatusError:
        # print(f"Hunter API HTTP Error. Falling back to mock.")
        return {"score": 40, "status": "api_error"}
    except httpx.RequestError:
        # print(f"Hunter API Request Error. Falling back to mock.")
        return {"score": 45, "status": "network_error"}
    except Exception:
        # print(f"Unexpected error during Hunter verification. Falling back to mock.")
        return {"score": 48, "status": "unexpected_error"}


# --- 6. FastAPI Application Setup & CORS ---

app = FastAPI(
    title="Contact Manager Backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# --- 7. CORS Configuration ---
origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Startup Event: DB Initialization ---
@app.on_event("startup")
async def on_startup():
    """Creates database tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Seed initial dummy data if DB is empty
    async with AsyncSessionLocal() as session:
        stmt_count = select(Contact).limit(1)
        result = await session.execute(stmt_count)
        if not result.scalars().first():
            # Mock verification for initial seed
            mock_score_1 = 85
            mock_score_2 = 45
            
            seed_contacts = [
                Contact(first_name="Alice", last_name="Smith", email="alice@example.com", phone="555-1234", hunter_score=mock_score_1),
                Contact(first_name="Bob", last_name="Johnson", email="bob.j@test.org", phone=None, hunter_score=mock_score_2),
            ]
            session.add_all(seed_contacts)
            await session.commit()
            # print("Seeded initial contacts.")


# --- 8. API Endpoints ---

# --- Verification Endpoint (Standalone) ---
@app.get("/contacts/verify-email/{email}", response_model=Dict[str, Any])
async def verify_email_endpoint(email: EmailStr):
    """Triggers Hunter.io verification for an email."""
    result = await verify_email_hunter(email)
    return {"email": email, "score": result['score'], "status": result['status']}


# --- CRUD Operations ---

@app.post("/contacts", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    contact_in: ContactCreate, 
    db: AsyncSession = Depends(get_db)
):
    """Create a new contact, verifying email score first."""
    
    # 1. Verify Email Score
    verification_result = await verify_email_hunter(contact_in.email)
    hunter_score = verification_result['score']
    
    # 2. Check for existing email (409 Conflict)
    stmt_check = select(Contact).where(Contact.email == contact_in.email)
    result_check = await db.execute(stmt_check)
    if result_check.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contact with email {contact_in.email} already exists."
        )

    # 3. Create DB Model instance
    db_contact = Contact(
        first_name=contact_in.first_name,
        last_name=contact_in.last_name,
        email=contact_in.email,
        phone=contact_in.phone,
        hunter_score=hunter_score
    )
    
    # 4. Save to DB
    db.add(db_contact)
    await db.commit()
    await db.refresh(db_contact)
    
    return db_contact


@app.get("/contacts", response_model=List[ContactResponse])
async def read_contacts(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100
):
    """Retrieve all contacts (supports optional query params for filtering/pagination)."""
    stmt = select(Contact).offset(skip).limit(limit).order_by(Contact.id)
    result = await db.execute(stmt)
    contacts = result.scalars().all()
    return contacts


@app.get("/contacts/{contact_id}", response_model=ContactResponse)
async def read_contact(contact_id: int, db: AsyncSession = Depends(get_db)):
    """Retrieve a single contact by ID."""
    stmt = select(Contact).where(Contact.id == contact_id)
    result = await db.execute(stmt)
    contact = result.scalars().first()
    
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )
    return contact


@app.put("/contacts/{contact_id}", response_model=ContactResponse)
async def update_contact_put(
    contact_id: int, 
    contact_in: ContactCreate, # PUT requires all fields, so we reuse Create schema
    db: AsyncSession = Depends(get_db)
):
    """Fully update an existing contact."""
    stmt_get = select(Contact).where(Contact.id == contact_id)
    result_get = await db.execute(stmt_get)
    db_contact = result_get.scalars().first()

    if db_contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )

    # Check for email conflict if the email has changed
    if db_contact.email != contact_in.email:
        stmt_check = select(Contact).where(Contact.email == contact_in.email)
        result_check = await db.execute(stmt_check)
        if result_check.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email {contact_in.email} is already in use by another contact."
            )
        
        # Re-verify score if email changed
        verification_result = await verify_email_hunter(contact_in.email)
        hunter_score = verification_result['score']
    else:
        # If email didn't change, keep existing score (optimization)
        hunter_score = db_contact.hunter_score

    # Update fields
    db_contact.first_name = contact_in.first_name
    db_contact.last_name = contact_in.last_name
    db_contact.email = contact_in.email
    db_contact.phone = contact_in.phone
    db_contact.hunter_score = hunter_score
    
    await db.commit()
    await db.refresh(db_contact)
    return db_contact


@app.patch("/contacts/{contact_id}", response_model=ContactResponse)
async def update_contact_patch(
    contact_id: int, 
    contact_in: ContactUpdate, 
    db: AsyncSession = Depends(get_db)
):
    """Partially update an existing contact."""
    stmt_get = select(Contact).where(Contact.id == contact_id)
    result_get = await db.execute(stmt_get)
    db_contact = result_get.scalars().first()

    if db_contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )

    update_data = contact_in.model_dump(exclude_unset=True)
    
    # Handle email change separately for conflict check and score update
    if 'email' in update_data and update_data['email'] != db_contact.email:
        # 1. Check for conflict
        stmt_check = select(Contact).where(Contact.email == update_data['email'])
        result_check = await db.execute(stmt_check)
        if result_check.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email {update_data['email']} is already in use by another contact."
            )
        
        # 2. Re-verify score
        verification_result = await verify_email_hunter(update_data['email'])
        update_data['hunter_score'] = verification_result['score']
    
    # Apply standard updates
    for key, value in update_data.items():
        setattr(db_contact, key, value)

    await db.commit()
    await db.refresh(db_contact)
    return db_contact


@app.delete("/contacts/{contact_id}", status_code=status.HTTP_200_OK)
async def delete_contact(contact_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a contact by ID."""
    stmt = delete(Contact).where(Contact.id == contact_id)
    result = await db.execute(stmt)
    
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )
        
    await db.commit()
    return {"message": "Contact deleted"}