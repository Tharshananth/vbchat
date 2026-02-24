"""Database models - Simplified version without context windows"""
from sqlalchemy import Column, String, Text, DateTime, Integer
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import uuid

Base = declarative_base()

class FeedbackInteraction(Base):
    """
    Store chat interactions and feedback
    """
    __tablename__ = 'feedback_interactions'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    message_id = Column(String, nullable=False, unique=True, index=True)
    
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Interaction data
    question = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    provider_used = Column(String)
    tokens_used = Column(Integer)
    
    # Feedback data
    feedback_type = Column(String)
    feedback_comment = Column(Text)
    feedback_timestamp = Column(DateTime)
    
    def __repr__(self):
        return f"<FeedbackInteraction(id={self.id}, timestamp={self.timestamp})>"