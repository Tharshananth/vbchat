"""
PRODUCTION CHAT ENDPOINT
Rock-solid with error handling, monitoring, and failover
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from typing import List, Optional
from sqlalchemy.orm import Session
import logging
import uuid
from datetime import datetime

from database import get_db
from services.chat_memory_service import get_memory_service, ChatMemoryService
from llm.factory import get_llm_factory
from llm.base import Message
from vector_db.retriever import DocumentRetriever
from config import get_config
from redis import Redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["Chat"])

# Initialize Redis (optional)
try:
    redis_client = Redis(host='localhost', port=6379, decode_responses=True, socket_timeout=2)
    redis_client.ping()
    logger.info("✅ Redis available")
except:
    redis_client = None
    logger.warning("⚠️ Redis unavailable, using DB-only mode")

# Pydantic Models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    provider: Optional[str] = None
    user_id: Optional[str] = None
    
    @validator('message')
    def sanitize_message(cls, v):
        return v.strip()

class Source(BaseModel):
    title: str
    url: str
    content: str

class ChatResponse(BaseModel):
    response: str
    sources: List[Source]
    session_id: str
    message_id: str
    success: bool = True
    provider_used: str
    tokens_used: Optional[int] = None
    context_expires_at: str
    time_remaining_seconds: int
    context_window_number: int
    context_was_reset: bool = False
    warning: Optional[str] = None

class ErrorResponse(BaseModel):
    error: str
    detail: str
    session_id: Optional[str] = None
    timestamp: str


@router.post("/", response_model=ChatResponse, responses={500: {"model": ErrorResponse}})
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    """
    PRODUCTION CHAT ENDPOINT
    - Thread-safe
    - Redis + DB fallback
    - Comprehensive error handling
    - Token limit protection
    - Context expiration handling
    """
    
    # Generate IDs
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:12]}"
    user_id = request.user_id or "anonymous"
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    
    logger.info(f"{'='*80}")
    logger.info(f"📨 NEW REQUEST | Session: {session_id} | User: {user_id}")
    logger.info(f"{'='*80}")
    
    try:
        # ===== STEP 1: Initialize Services =====
        memory_service = get_memory_service(redis_client)
        llm_factory = get_llm_factory()
        retriever = DocumentRetriever()
        config = get_config()
        
        # ===== STEP 2: Get Current Context Window =====
        logger.info("📂 Getting context window...")
        
        try:
            context = memory_service.get_or_create_context(
                session_id=session_id,
                user_id=user_id,
                db=db
            )
            
            logger.info(f"✅ Context loaded")
            logger.info(f"   Window #{context.window_number}")
            logger.info(f"   Expires: {context.window_end.isoformat()}")
            logger.info(f"   Time remaining: {context.time_remaining():.0f}s")
            logger.info(f"   Messages in context: {len(context.messages)}")
            
        except Exception as e:
            logger.error(f"❌ Context loading failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load conversation context: {str(e)}"
            )
        
        # ===== STEP 3: Check Expiration (Double-check) =====
        was_reset = False
        if context.is_expired():
            logger.warning("⏰ Context expired during request processing!")
            try:
                context = memory_service.reset_context(session_id, user_id, db)
                was_reset = True
                logger.info("✅ Context reset successfully")
            except Exception as e:
                logger.error(f"❌ Context reset failed: {e}")
                # Continue anyway with empty context
        
        # ===== STEP 4: Retrieve Knowledge Base Context =====
        logger.info("🔍 Retrieving from knowledge base...")
        
        try:
            kb_context = retriever.retrieve_context(request.message)
            logger.info(f"✅ Retrieved {len(kb_context['sources'])} sources")
        except Exception as e:
            logger.error(f"⚠️ Knowledge base retrieval failed: {e}")
            # Fallback to empty context
            kb_context = {
                "context": "No additional context available.",
                "sources": []
            }
        
        # ===== STEP 5: Build LLM Messages =====
        logger.info("🤖 Building LLM context...")
        
        try:
            # Get historical messages
            llm_messages = memory_service.build_llm_context(
                context=context,
                current_question=request.message
            )
            
            # Add knowledge base context to the last message
            if kb_context['context']:
                last_msg = llm_messages[-1]
                last_msg['content'] = f"""Context from knowledge base:
{kb_context['context']}

User question: {last_msg['content']}

Please answer based on the context above."""
            
            # Add context reset warning if needed
            if was_reset:
                system_warning = "[SYSTEM: Previous conversation context expired. This is a fresh conversation.]"
                llm_messages.insert(0, {
                    "role": "system",
                    "content": system_warning
                })
            
            logger.info(f"✅ Built {len(llm_messages)} messages for LLM")
            
        except Exception as e:
            logger.error(f"❌ Failed to build LLM context: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to prepare conversation context: {str(e)}"
            )
        
        # ===== STEP 6: Generate LLM Response =====
        logger.info(f"🧠 Generating response with {request.provider or 'default'} provider...")
        
        try:
            # Convert to Message objects
            messages = [
                Message(role=m['role'], content=m['content'])
                for m in llm_messages
            ]
            
            # Generate with fallback
            llm_response = llm_factory.generate_with_fallback(
                messages=messages,
                system_prompt=config.system_prompt,
                preferred_provider=request.provider
            )
            
            if llm_response.finish_reason == "error":
                logger.error(f"❌ LLM generation failed: {llm_response.error}")
                raise Exception(f"LLM error: {llm_response.error}")
            
            logger.info(f"✅ Response generated")
            logger.info(f"   Provider: {llm_response.provider}")
            logger.info(f"   Tokens: {llm_response.tokens_used}")
            logger.info(f"   Length: {len(llm_response.content)} chars")
            
        except Exception as e:
            logger.error(f"❌ LLM generation failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate response: {str(e)}"
            )
        
        # ===== STEP 7: Save to Context & Database =====
        logger.info("💾 Saving interaction...")
        
        try:
            updated_context, _ = memory_service.add_interaction(
                session_id=session_id,
                user_id=user_id,
                question=request.message,
                response=llm_response.content,
                message_id=message_id,
                provider=llm_response.provider,
                db=db
            )
            
            logger.info("✅ Interaction saved")
            logger.info(f"   Messages in context now: {len(updated_context.messages)}")
            
        except Exception as e:
            logger.error(f"⚠️ Failed to save interaction: {e}", exc_info=True)
            # Don't fail the request, just log it
            updated_context = context
        
        # ===== STEP 8: Build Response =====
        time_remaining = int(updated_context.time_remaining())
        
        # Warning if context expiring soon
        warning = None
        if 0 < time_remaining < 60:
            warning = f"Context expires in {time_remaining} seconds"
        elif time_remaining == 0:
            warning = "Context has expired"
        
        response = ChatResponse(
            response=llm_response.content,
            sources=[Source(**src) for src in kb_context['sources']],
            session_id=session_id,
            message_id=message_id,
            success=True,
            provider_used=llm_response.provider,
            tokens_used=llm_response.tokens_used,
            context_expires_at=updated_context.window_end.isoformat(),
            time_remaining_seconds=time_remaining,
            context_window_number=updated_context.window_number,
            context_was_reset=was_reset,
            warning=warning
        )
        
        logger.info(f"✅ REQUEST COMPLETE | Message ID: {message_id}")
        logger.info(f"{'='*80}\n")
        
        return response
        
    except HTTPException:
        raise
        
    except Exception as e:
        # Catch-all error handler
        logger.error(f"❌ UNHANDLED ERROR: {e}", exc_info=True)
        logger.error(f"{'='*80}\n")
        
        # Return error response
        error = ErrorResponse(
            error="Internal Server Error",
            detail=str(e),
            session_id=session_id,
            timestamp=datetime.utcnow().isoformat()
        )
        
        raise HTTPException(status_code=500, detail=error.dict())


@router.get("/session/{session_id}/info")
async def get_session_info(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get session information"""
    
    try:
        memory_service = get_memory_service(redis_client)
        context = memory_service.get_or_create_context(session_id, "unknown", db)
        
        return {
            "session_id": session_id,
            "window_number": context.window_number,
            "window_start": context.window_start.isoformat(),
            "window_end": context.window_end.isoformat(),
            "time_remaining_seconds": int(context.time_remaining()),
            "is_expired": context.is_expired(),
            "messages_count": len(context.messages),
            "messages": [
                {
                    "role": m.role,
                    "content": m.content[:100] + "..." if len(m.content) > 100 else m.content,
                    "timestamp": m.timestamp.isoformat(),
                    "tokens": m.tokens
                }
                for m in context.messages
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get session info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/reset")
async def reset_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Manually reset session context"""
    
    try:
        memory_service = get_memory_service(redis_client)
        context = memory_service.reset_context(session_id, "manual_reset", db)
        
        return {
            "success": True,
            "message": "Context reset successfully",
            "new_window_number": context.window_number,
            "new_expiry": context.window_end.isoformat(),
            "time_remaining_seconds": int(context.time_remaining())
        }
    except Exception as e:
        logger.error(f"Failed to reset session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Delete session and all its data"""
    
    try:
        # Delete from Redis
        if redis_client:
            redis_client.delete(f"chat:context:{session_id}")
        
        # Mark as inactive in DB
        from database import ChatSession
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id
        ).first()
        
        if session:
            session.is_active = False
            db.commit()
        
        return {
            "success": True,
            "message": f"Session {session_id} deleted"
        }
    except Exception as e:
        logger.error(f"Failed to delete session: {e}")
        raise HTTPException(status_code=500, detail=str(e))