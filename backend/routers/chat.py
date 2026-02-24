"""
Simplified Chat Endpoint with Configurable LangChain Memory
Uses settings from config.yaml for buffer window size and token limits
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
import logging
import uuid
from datetime import datetime

from database import get_db, FeedbackInteraction
from llm.factory import get_llm_factory
from llm.base import Message
from vector_db.retriever import DocumentRetriever
from config import get_config, get_conversation_memory_config
from langchain.memory import ConversationBufferWindowMemory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["Chat"])

# In-memory session storage for LangChain memory
session_memories: Dict[str, ConversationBufferWindowMemory] = {}

def get_or_create_memory(session_id: str) -> ConversationBufferWindowMemory:
    """Get or create conversation memory for session using config settings"""
    if session_id not in session_memories:
        # Load memory configuration
        memory_config = get_conversation_memory_config()
        buffer_config = memory_config.buffer_window
        
        # Create memory with configured settings
        session_memories[session_id] = ConversationBufferWindowMemory(
            k=buffer_config.k,  # From config
            return_messages=buffer_config.return_messages,
            memory_key=buffer_config.memory_key
        )
        
        logger.info(f"Created memory for session {session_id} with k={buffer_config.k}, max_tokens={buffer_config.max_tokens}")
    
    return session_memories[session_id]

def count_tokens_in_messages(messages: List[Dict]) -> int:
    """
    Simple token counting for messages
    Approximate: 4 characters = 1 token
    """
    total_chars = sum(len(msg.get('content', '')) for msg in messages)
    return total_chars // 4

def check_token_limit(messages: List[Dict], max_tokens: int, warning_threshold: float) -> Dict[str, any]:
    """
    Check if messages are approaching token limit
    Returns: dict with warning info
    """
    token_count = count_tokens_in_messages(messages)
    warning_level = token_count / max_tokens
    
    result = {
        'token_count': token_count,
        'max_tokens': max_tokens,
        'percentage': warning_level * 100,
        'warning': warning_level >= warning_threshold,
        'exceeds_limit': token_count > max_tokens
    }
    
    return result

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

class TokenInfo(BaseModel):
    message_tokens: int
    history_tokens: int
    total_tokens: int
    max_tokens: int
    percentage: float
    warning: bool

class ChatResponse(BaseModel):
    response: str
    sources: List[Source]
    session_id: str
    message_id: str
    success: bool = True
    provider_used: str
    tokens_used: Optional[int] = None
    token_info: Optional[TokenInfo] = None

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
    Chat endpoint with configurable LangChain conversation memory
    - Stores last k Q&A exchanges (configured in config.yaml)
    - Monitors token usage against configured limits
    - No time-based context expiration
    """
    
    # Generate IDs
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:12]}"
    user_id = request.user_id or "anonymous"
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    
    logger.info(f"Chat request | Session: {session_id} | User: {user_id}")
    
    try:
        # Initialize services and config
        llm_factory = get_llm_factory()
        retriever = DocumentRetriever()
        config = get_config()
        memory_config = get_conversation_memory_config()
        buffer_config = memory_config.buffer_window
        token_config = memory_config.token_counting
        
        memory = get_or_create_memory(session_id)
        
        # Retrieve knowledge base context
        logger.info("Retrieving from knowledge base...")
        try:
            kb_context = retriever.retrieve_context(request.message)
            logger.info(f"Retrieved {len(kb_context['sources'])} sources")
        except Exception as e:
            logger.error(f"Knowledge base retrieval failed: {e}")
            kb_context = {
                "context": "No additional context available.",
                "sources": []
            }
        
        # Build messages for LLM
        messages = []
        
        # Add conversation history from memory
        history = memory.load_memory_variables({})
        if history and buffer_config.memory_key in history:
            for msg in history[buffer_config.memory_key]:
                messages.append({
                    "role": "user" if msg.type == "human" else "assistant",
                    "content": msg.content
                })
        
        # Check token usage in history
        history_token_count = count_tokens_in_messages(messages)
        
        # Add current question with context
        current_content = request.message
        if kb_context['context']:
            current_content = f"""Context from knowledge base:
{kb_context['context']}

User question: {request.message}

Please answer based on the context above."""
        
        messages.append({
            "role": "user",
            "content": current_content
        })
        
        # Check total token usage
        if token_config.enabled:
            token_check = check_token_limit(
                messages, 
                buffer_config.max_tokens,
                token_config.warning_threshold
            )
            
            if token_check['exceeds_limit']:
                logger.warning(f"Token limit exceeded: {token_check['token_count']} > {buffer_config.max_tokens}")
                # Trim oldest messages
                messages = messages[-(buffer_config.k * 2 + 1):]
                logger.info(f"Trimmed to {len(messages)} messages")
            
            elif token_check['warning']:
                logger.warning(f"Approaching token limit: {token_check['percentage']:.1f}%")
        
        logger.info(f"Built {len(messages)} messages for LLM")
        
        # Generate LLM response
        logger.info(f"Generating response with {request.provider or 'default'} provider...")
        
        try:
            # Convert to Message objects
            llm_messages = [
                Message(role=m['role'], content=m['content'])
                for m in messages
            ]
            
            # Generate with fallback
            llm_response = llm_factory.generate_with_fallback(
                messages=llm_messages,
                system_prompt=config.system_prompt,
                preferred_provider=request.provider
            )
            
            if llm_response.finish_reason == "error":
                logger.error(f"LLM generation failed: {llm_response.error}")
                raise Exception(f"LLM error: {llm_response.error}")
            
            logger.info(f"Response generated | Provider: {llm_response.provider} | Tokens: {llm_response.tokens_used}")
            
        except Exception as e:
            logger.error(f"LLM generation failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate response: {str(e)}"
            )
        
        # Save to memory
        memory.save_context(
            {"input": request.message},
            {"output": llm_response.content}
        )
        logger.info("Saved to conversation memory")
        
        # Save to database
        try:
            interaction = FeedbackInteraction(
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                timestamp=datetime.utcnow(),
                question=request.message,
                response=llm_response.content,
                provider_used=llm_response.provider,
                tokens_used=llm_response.tokens_used
            )
            
            db.add(interaction)
            db.commit()
            db.refresh(interaction)
            
            logger.info("Saved to database")
            
        except Exception as e:
            logger.error(f"Failed to save to database: {e}", exc_info=True)
            # Don't fail the request
        
        # Calculate final token info
        message_tokens = count_tokens_in_messages([{"content": request.message}])
        response_tokens = count_tokens_in_messages([{"content": llm_response.content}])
        total_tokens = history_token_count + message_tokens + response_tokens
        
        token_info = TokenInfo(
            message_tokens=message_tokens,
            history_tokens=history_token_count,
            total_tokens=total_tokens,
            max_tokens=buffer_config.max_tokens,
            percentage=(total_tokens / buffer_config.max_tokens) * 100,
            warning=total_tokens >= (buffer_config.max_tokens * token_config.warning_threshold)
        )
        
        # Build response
        response = ChatResponse(
            response=llm_response.content,
            sources=[Source(**src) for src in kb_context['sources']],
            session_id=session_id,
            message_id=message_id,
            success=True,
            provider_used=llm_response.provider,
            tokens_used=llm_response.tokens_used,
            token_info=token_info
        )
        
        logger.info(f"Request complete | Message ID: {message_id}")
        
        return response
        
    except HTTPException:
        raise
        
    except Exception as e:
        logger.error(f"Unhandled error: {e}", exc_info=True)
        
        error = ErrorResponse(
            error="Internal Server Error",
            detail=str(e),
            session_id=session_id,
            timestamp=datetime.utcnow().isoformat()
        )
        
        raise HTTPException(status_code=500, detail=error.dict())


@router.get("/memory/info/{session_id}")
async def get_memory_info(session_id: str):
    """Get memory configuration and current state for a session"""
    
    memory_config = get_conversation_memory_config()
    buffer_config = memory_config.buffer_window
    token_config = memory_config.token_counting
    
    info = {
        "session_id": session_id,
        "config": {
            "type": memory_config.type,
            "buffer_window_k": buffer_config.k,
            "max_tokens": buffer_config.max_tokens,
            "memory_key": buffer_config.memory_key,
            "token_counting_enabled": token_config.enabled,
            "warning_threshold": token_config.warning_threshold
        },
        "session_exists": session_id in session_memories
    }
    
    if session_id in session_memories:
        memory = session_memories[session_id]
        history = memory.load_memory_variables({})
        
        if history and buffer_config.memory_key in history:
            messages = history[buffer_config.memory_key]
            message_list = [
                {
                    "type": msg.type,
                    "content": msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                }
                for msg in messages
            ]
            
            # Calculate tokens
            full_messages = [{"content": msg.content} for msg in messages]
            token_count = count_tokens_in_messages(full_messages)
            
            info["current_state"] = {
                "message_count": len(messages),
                "messages": message_list,
                "estimated_tokens": token_count,
                "token_percentage": (token_count / buffer_config.max_tokens) * 100
            }
        else:
            info["current_state"] = {
                "message_count": 0,
                "messages": [],
                "estimated_tokens": 0,
                "token_percentage": 0
            }
    
    return info


@router.get("/history/{session_id}")
async def get_chat_history(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get chat history for a session from database"""
    
    try:
        interactions = db.query(FeedbackInteraction).filter(
            FeedbackInteraction.session_id == session_id
        ).order_by(FeedbackInteraction.timestamp.asc()).all()
        
        history = []
        for interaction in interactions:
            history.append({
                "message_id": interaction.message_id,
                "timestamp": interaction.timestamp.isoformat(),
                "question": interaction.question,
                "response": interaction.response,
                "provider": interaction.provider_used,
                "feedback_type": interaction.feedback_type
            })
        
        return {
            "session_id": session_id,
            "message_count": len(history),
            "history": history
        }
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/history/{session_id}")
async def delete_chat_history(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Delete chat history for a session"""
    
    try:
        # Delete from memory
        if session_id in session_memories:
            del session_memories[session_id]
        
        # Delete from database
        deleted = db.query(FeedbackInteraction).filter(
            FeedbackInteraction.session_id == session_id
        ).delete()
        
        db.commit()
        
        return {
            "success": True,
            "message": f"Deleted {deleted} messages from session {session_id}"
        }
    except Exception as e:
        logger.error(f"Failed to delete history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear/{session_id}")
async def clear_session_memory(session_id: str):
    """Clear in-memory conversation history for a session"""
    
    try:
        if session_id in session_memories:
            del session_memories[session_id]
            return {
                "success": True,
                "message": f"Cleared memory for session {session_id}"
            }
        else:
            return {
                "success": True,
                "message": f"No memory found for session {session_id}"
            }
    except Exception as e:
        logger.error(f"Failed to clear memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))