// Configuration - Update these URLs with your actual Lambda Function URLs
const CONFIG = {
    SUMMARIZE_URL: 'YOUR_SUMMARIZE_LAMBDA_FUNCTION_URL',
    CHAT_URL: 'YOUR_CHAT_LAMBDA_FUNCTION_URL'
};

// Session management
let sessionId = localStorage.getItem('sessionId');
if (!sessionId) {
    sessionId = generateUUID();
    localStorage.setItem('sessionId', sessionId);
}

function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// API helper function
async function callLambda(url, data) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    });
    
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    return response.json();
}

// UI helper functions
function showError(message) {
    const errorAlert = document.getElementById('error-alert');
    errorAlert.textContent = message;
    errorAlert.style.display = 'block';
    
    // Hide after 5 seconds
    setTimeout(() => {
        errorAlert.style.display = 'none';
    }, 5000);
}

function showSuccess(message) {
    const successAlert = document.getElementById('success-alert');
    successAlert.textContent = message;
    successAlert.style.display = 'block';
    
    // Hide after 3 seconds
    setTimeout(() => {
        successAlert.style.display = 'none';
    }, 3000);
}

function hideAlerts() {
    document.getElementById('error-alert').style.display = 'none';
    document.getElementById('success-alert').style.display = 'none';
}

function setLoading(elementId, isLoading) {
    const button = document.getElementById(elementId);
    const spinner = document.getElementById(elementId.replace('-btn', '-spinner'));
    const text = document.getElementById(elementId.replace('-btn', '-text'));
    
    if (isLoading) {
        button.disabled = true;
        spinner.style.display = 'inline-block';
        text.textContent = 'Processing...';
    } else {
        button.disabled = false;
        spinner.style.display = 'none';
        text.textContent = elementId === 'summarize-btn' ? 'Summarize' : 'Send';
    }
}

function appendChatMessage(role, text) {
    const chatLog = document.getElementById('chat-log');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'chat-msg';
    
    const roleSpan = document.createElement('span');
    roleSpan.className = 'role';
    roleSpan.textContent = role === 'user' ? 'You:' : 'Assistant:';
    
    const textSpan = document.createElement('span');
    textSpan.innerHTML = text;
    
    messageDiv.appendChild(roleSpan);
    messageDiv.appendChild(textSpan);
    chatLog.appendChild(messageDiv);
    chatLog.scrollTop = chatLog.scrollHeight;
}

function setChatStatus(message) {
    const statusElement = document.getElementById('chat-status');
    statusElement.textContent = message || '';
}

// Main functionality
async function handleSummarize(event) {
    event.preventDefault();
    hideAlerts();
    
    const paperUrl = document.getElementById('paper_url').value.trim();
    const complexity = document.querySelector('input[name="complexity"]:checked').value;
    
    if (!paperUrl) {
        showError('Please enter a paper URL');
        return;
    }
    
    setLoading('summarize-btn', true);
    
    try {
        const response = await callLambda(CONFIG.SUMMARIZE_URL, {
            paper_url: paperUrl,
            complexity: complexity,
            session_id: sessionId
        });
        
        if (response.success) {
            // Show results section
            document.getElementById('results-section').style.display = 'block';
            
            // Update summary content
            document.getElementById('summary-level').textContent = response.level;
            document.getElementById('summary-content').innerHTML = response.summary;
            document.getElementById('source-link').href = response.paper_url;
            
            // Clear chat log for new paper
            document.getElementById('chat-log').innerHTML = '';
            setChatStatus('');
            
            showSuccess('Paper summarized successfully!');
        } else {
            showError(response.error || 'Failed to summarize paper');
        }
    } catch (error) {
        console.error('Error:', error);
        showError('Error summarizing paper: ' + error.message);
    } finally {
        setLoading('summarize-btn', false);
    }
}

async function handleChat() {
    const chatInput = document.getElementById('chat-input');
    const message = chatInput.value.trim();
    const paperUrl = document.getElementById('paper_url').value.trim();
    
    if (!message) return;
    if (!paperUrl) {
        showError('Please summarize a paper first');
        return;
    }
    
    // Add user message to chat
    appendChatMessage('user', message);
    chatInput.value = '';
    setChatStatus('Thinking...');
    setLoading('chat-send', true);
    
    try {
        const response = await callLambda(CONFIG.CHAT_URL, {
            paper_url: paperUrl,
            message: message,
            session_id: sessionId
        });
        
        if (response.success) {
            appendChatMessage('model', response.answer);
            setChatStatus('');
        } else {
            setChatStatus(response.error || 'Error generating response');
        }
    } catch (error) {
        console.error('Chat error:', error);
        setChatStatus('Network error: ' + error.message);
    } finally {
        setLoading('chat-send', false);
    }
}

// Event listeners
window.addEventListener('DOMContentLoaded', () => {
    // Summarize form
    document.getElementById('summarize-form').addEventListener('submit', handleSummarize);
    
    // Chat functionality
    const chatSendBtn = document.getElementById('chat-send');
    const chatInput = document.getElementById('chat-input');
    
    if (chatSendBtn) {
        chatSendBtn.addEventListener('click', handleChat);
    }
    
    if (chatInput) {
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                handleChat();
            }
        });
    }
    
    // Configuration check
    if (CONFIG.SUMMARIZE_URL === 'YOUR_SUMMARIZE_LAMBDA_FUNCTION_URL') {
        showError('Please update the Lambda function URLs in main.js before using the application');
    }
});
