import React, { useState, useRef, useEffect } from 'react';
import './Chatbot.css';

const Chatbot = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      id: 1,
      text: "Welcome! How may I assist you today?",
      sender: "bot",
      timestamp: new Date()
    }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [feedbackModal, setFeedbackModal] = useState(null);
  const [feedbackText, setFeedbackText] = useState('');
  const messagesEndRef = useRef(null);

  const API_BASE_URL = "http://localhost:8000";

  useEffect(() => {
    if (!sessionId) {
      setSessionId(`session_${Date.now()}`);
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const sendMessage = async () => {
    if (!input.trim()) return;

    const userMessage = {
      id: Date.now(),
      text: input,
      sender: "user",
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsTyping(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/chat/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: input,
          session_id: sessionId,
          user_id: `user_${Date.now()}`
        })
      });

      const data = await response.json();

      const botMessage = {
        id: Date.now() + 1,
        text: data.response,
        sender: "bot",
        timestamp: new Date(),
        messageId: data.message_id,
        sources: data.sources || []
      };

      setMessages(prev => [...prev, botMessage]);
    } catch (error) {
      console.error('Error:', error);
      const errorMessage = {
        id: Date.now() + 1,
        text: "Sorry, I'm having trouble connecting. Please try again.",
        sender: "bot",
        timestamp: new Date(),
        isError: true
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleFeedback = async (messageId, feedbackType) => {
    try {
      await fetch(`${API_BASE_URL}/api/feedback/submit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message_id: messageId,
          feedback_type: feedbackType
        })
      });

      setMessages(prev => prev.map(msg =>
        msg.messageId === messageId
          ? { ...msg, feedback: feedbackType }
          : msg
      ));
    } catch (error) {
      console.error('Feedback error:', error);
    }
  };

  const handleDetailedFeedback = async () => {
    if (!feedbackText.trim() || !feedbackModal) return;

    try {
      await fetch(`${API_BASE_URL}/api/feedback/submit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message_id: feedbackModal,
          feedback_type: 'detailed_feedback',
          feedback_text: feedbackText
        })
      });

      setMessages(prev => prev.map(msg =>
        msg.messageId === feedbackModal
          ? { ...msg, feedback: 'detailed', feedbackText: feedbackText }
          : msg
      ));

      setFeedbackModal(null);
      setFeedbackText('');
    } catch (error) {
      console.error('Detailed feedback error:', error);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearChat = () => {
    setMessages([
      {
        id: 1,
        text: "Welcome! How may I assist you today?",
        sender: "bot",
        timestamp: new Date()
      }
    ]);
    setSessionId(`session_${Date.now()}`);
  };

  return (
    <>
      {isOpen && (
        <div className="chatbot-container">
          <div className="chatbot-header">
            <div className="header-content">
              <div className="bot-avatar-small">
                <div className="bot-face">
                  <div className="bot-eyes">
                    <div className="bot-eye"></div>
                    <div className="bot-eye"></div>
                  </div>
                </div>
              </div>
            </div>
            <div className="header-actions">
              <button onClick={clearChat} className="clear-btn" title="Clear chat">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" strokeWidth="2" strokeLinecap="round"/>
                </svg>
              </button>
              <button onClick={() => setIsOpen(false)} className="close-btn">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path d="M6 18L18 6M6 6l12 12" strokeWidth="2" strokeLinecap="round"/>
                </svg>
              </button>
            </div>
          </div>

          <div className="chatbot-messages">
            {messages.map((message, index) => (
              <div key={message.id} className={`message-wrapper ${message.sender}`}>
                {message.sender === 'bot' && (
                  <div className="bot-avatar-message">
                    <div className="bot-face-small">
                      <div className="bot-eyes-small">
                        <div className="bot-eye-small"></div>
                        <div className="bot-eye-small"></div>
                      </div>
                    </div>
                  </div>
                )}
                
                <div className={`message ${message.sender} ${message.isError ? 'error' : ''}`}>
                  <div className="message-text">{message.text}</div>
                  
                  {message.sender === 'bot' && message.messageId && !message.feedback && (
                    <div className="feedback-buttons">
                      <button 
                        onClick={() => handleFeedback(message.messageId, 'thumbs_up')}
                        className="feedback-btn"
                        title="Helpful"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                          <path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3" strokeWidth="2" strokeLinecap="round"/>
                        </svg>
                      </button>
                      <button 
                        onClick={() => handleFeedback(message.messageId, 'thumbs_down')}
                        className="feedback-btn"
                        title="Not helpful"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                          <path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3zm7-13h2.67A2.31 2.31 0 0122 4v7a2.31 2.31 0 01-2.33 2H17" strokeWidth="2" strokeLinecap="round"/>
                        </svg>
                      </button>
                      <button 
                        onClick={() => setFeedbackModal(message.messageId)}
                        className="feedback-btn write-feedback"
                        title="Write detailed feedback"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                          <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" strokeWidth="2" strokeLinecap="round"/>
                          <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" strokeWidth="2" strokeLinecap="round"/>
                        </svg>
                      </button>
                    </div>
                  )}

                  {message.feedback && (
                    <div className="feedback-given">
                      {message.feedback === 'thumbs_up' ? '👍' : message.feedback === 'thumbs_down' ? '👎' : '✏️'} 
                      {message.feedbackText ? `Feedback: "${message.feedbackText}"` : 'Feedback submitted'}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {isTyping && (
              <div className="message-wrapper bot">
                <div className="bot-avatar-message">
                  <div className="bot-face-small">
                    <div className="bot-eyes-small">
                      <div className="bot-eye-small"></div>
                      <div className="bot-eye-small"></div>
                    </div>
                  </div>
                </div>
                <div className="message bot typing">
                  <div className="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <div className="chatbot-input">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Ask a question..."
              disabled={isTyping}
            />
            <button 
              onClick={sendMessage} 
              disabled={!input.trim() || isTyping}
              className="send-btn"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          </div>
        </div>
      )}

      {feedbackModal && (
        <div className="feedback-modal-overlay">
          <div className="feedback-modal">
            <h3>Write Your Feedback</h3>
            <textarea
              value={feedbackText}
              onChange={(e) => setFeedbackText(e.target.value)}
              placeholder="Please share your feedback on this response..."
              className="feedback-textarea"
              maxLength={500}
            />
            <div className="feedback-modal-footer">
              <span className="char-count">{feedbackText.length}/500</span>
              <div className="buttons">
                <button 
                  onClick={() => {
                    setFeedbackModal(null);
                    setFeedbackText('');
                  }}
                  className="modal-btn cancel-btn"
                >
                  Cancel
                </button>
                <button 
                  onClick={handleDetailedFeedback}
                  disabled={!feedbackText.trim()}
                  className="modal-btn submit-btn"
                >
                  Submit Feedback
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <button 
        className={`chatbot-toggle ${isOpen ? 'open' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
      >
        {isOpen ? (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path d="M6 18L18 6M6 6l12 12" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        ) : (
          <div className="bot-avatar-toggle">
            <div className="bot-face-toggle">
              <div className="bot-eyes-toggle">
                <div className="bot-eye-toggle"></div>
                <div className="bot-eye-toggle"></div>
              </div>
              <div className="bot-smile"></div>
            </div>
          </div>
        )}
      </button>
    </>
  );
};

export default Chatbot;