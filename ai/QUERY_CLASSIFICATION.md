# 🎯 Query Classification System

## Overview

The RAG system now uses **intelligent query classification** to determine if document retrieval is needed, significantly improving response times for non-document queries.

## How It Works

### Three-Step Process

```
User Query → Step 0: Query Classification → Fast Path OR RAG Path
```

#### **Step 0: Query Classification**
The LLM classifies queries into three categories:

| Category | Description | Examples | Action |
|----------|-------------|----------|--------|
| **greeting** | Simple greetings, pleasantries | "hello!", "hi", "how are you?" | Fast response |
| **general** | Questions about the system itself | "what can you do?", "how does this work?" | Fast response |
| **document** | Questions needing document retrieval | "what's in sales.txt?", "how many TCO files?" | Full RAG pipeline |

#### **Fast Path (greeting/general)**
- No vector search
- No embedding generation
- No document retrieval
- Direct LLM response
- **Response time: ~1-2 seconds**

#### **RAG Path (document)**
- Query classification → File selection → Vector search → Context building → LLM generation
- Full retrieval pipeline
- **Response time: ~5-10 seconds**

---

## Performance Comparison

### Before (No Classification)

| Query | Processing | Time |
|-------|------------|------|
| "hello!" | Full RAG pipeline ❌ | ~8-10s |
| "what can you do?" | Full RAG pipeline ❌ | ~8-10s |
| "what's in sales.txt?" | Full RAG pipeline ✅ | ~8-10s |

**Problem**: Greetings and general queries trigger expensive document retrieval unnecessarily.

### After (With Classification)

| Query | Processing | Time |
|-------|------------|------|
| "hello!" | Fast path ✅ | ~1-2s ⚡ |
| "what can you do?" | Fast path ✅ | ~1-2s ⚡ |
| "what's in sales.txt?" | RAG pipeline ✅ | ~8-10s |

**Benefit**: 75-80% faster for non-document queries!

---

## Query Flow

### Before Classification
```
Every Query
    ↓
Classify Files (LLM call)
    ↓
Generate Embeddings (expensive)
    ↓
Vector Search (expensive)
    ↓
Retrieve Chunks
    ↓
Generate Answer
    ↓
Response (8-10s)
```

### After Classification
```
Query → Classify Type (LLM call)
         ↓
    ┌────┴────┐
    ↓         ↓
Greeting   Document
/General    Query
    ↓         ↓
Direct    File Selection
Response    ↓
(1-2s)    Embeddings
          ↓
          Vector Search
          ↓
          Retrieve
          ↓
          Answer
          ↓
          Response (8-10s)
```

---

## Classification Examples

### ✅ **Correctly Classified as GREETING**
```
- "hello!"
- "hi there"
- "good morning"
- "how are you?"
- "thanks"
- "goodbye"
- "hey"
```

### ✅ **Correctly Classified as GENERAL**
```
- "what can you do?"
- "how does this work?"
- "tell me about yourself"
- "who made you?"
- "what features do you have?"
- "can you help me?"
```

### ✅ **Correctly Classified as DOCUMENT**
```
- "what's in the sales report?"
- "how many TCO documents?"
- "list all files"
- "summarize REQUEST LETTER"
- "compare TCO and PES"
- "files about meetings"
- "how many delivery receipts?"
```

---

## Test Results

From `tests/test_agentic_selection.py`:

```
TEST 6: Query Classification
✅ 'hello!' → greeting
✅ 'hi there' → greeting
✅ 'how are you?' → greeting
✅ 'what can you do?' → general
✅ 'how does this work?' → general
✅ 'tell me about yourself' → general
✅ 'what's in the sales report?' → document
✅ 'how many TCO documents?' → document
✅ 'list all files' → document
✅ 'summarize REQUEST LETTER' → document

📊 Accuracy: 100% (10/10 correct)
```

---

## Implementation Details

### Classification Prompt

```python
classification_prompt = f"""You are a query classification AI. Classify the user's query into ONE of these categories:

USER QUERY: "{question}"

CATEGORIES:
1. greeting - Simple greetings, pleasantries, or introductions
2. general - General questions NOT about documents, or questions about the AI itself
3. document - Questions that need document retrieval to answer

INSTRUCTIONS:
- Respond with ONLY ONE WORD: "greeting", "general", or "document"
- If the query mentions files, documents, or specific information, return "document"
- If casual conversation or about the system, return "greeting" or "general"

YOUR CLASSIFICATION (ONE WORD):"""
```

### Response Generation

#### For Greetings
```python
prompt = f"""You are a helpful AI assistant for a document management system. 
Respond to this greeting naturally and warmly.

User: {question}

Keep your response brief (1-2 sentences) and friendly."""
```

#### For General Queries
```python
prompt = f"""You are a helpful AI assistant for a document management system. 
Answer this general question.

User: {question}

Instructions:
- Explain capabilities: search documents, answer questions, list files, compare
- Be concise and helpful"""
```

#### For Document Queries
Full RAG pipeline with:
1. File selection
2. Vector search
3. Chunk retrieval
4. Context building
5. LLM generation

---

## Backend Logs

### Fast Path (Greeting)
```
INFO: 🔍 Query classified as: GREETING
INFO: ⚡ Fast response (no retrieval): 1.23s
```

### Fast Path (General)
```
INFO: 🔍 Query classified as: GENERAL
INFO: ⚡ Fast response (no retrieval): 1.45s
```

### RAG Path (Document)
```
INFO: 🔍 Query classified as: DOCUMENT
INFO: 📚 Document query detected, starting RAG pipeline...
INFO: 🤖 LLM file selection response: 2,3,5
INFO: 🎯 LLM selected 3 specific files
INFO: ✅ Prioritized 15 chunks from 3 LLM-selected files
INFO: 📊 Specific query: showing 3 LLM-selected file sources
```

---

## Benefits

### 1. **Performance**
- 75-80% faster response for greetings/general
- No unnecessary vector searches
- Reduced embedding generation costs

### 2. **User Experience**
- Instant responses for casual queries
- No lag when saying "hello"
- Natural conversation flow

### 3. **Cost Efficiency**
- Fewer embedding API calls
- Less vector DB operations
- Lower computational overhead

### 4. **Scalability**
- Can handle more concurrent users
- Reduced server load
- Better resource utilization

---

## Edge Cases

### Ambiguous Queries

If classification is uncertain, the system defaults to `document` (safe fallback):

```python
if classification in ['greeting', 'general', 'document']:
    return classification
else:
    logger.warning(f"Unexpected classification, defaulting to 'document'")
    return 'document'
```

This ensures:
- No missed document queries
- Users always get relevant information
- Graceful degradation on errors

---

## Configuration

No additional configuration needed! Uses the same LLM provider:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-2.5-flash  # Fast classification
```

---

## Testing

Run the classification tests:

```bash
cd ai
python tests/test_agentic_selection.py
```

Look for **Test 6: Query Classification** results.

---

## Future Improvements

### 1. **Caching Classifications**
- Cache common greetings ("hello", "hi")
- Skip LLM call for cached queries
- Even faster responses (~0.1s)

### 2. **Intent Detection**
- Detect user intent beyond classification
- "Create", "Update", "Delete" intents
- Route to appropriate handlers

### 3. **Confidence Scores**
- LLM returns confidence with classification
- Threshold-based routing
- Better handling of ambiguous queries

### 4. **Multi-Intent Queries**
- Handle mixed queries: "Hello! What's in sales.txt?"
- Split into greeting + document
- Respond to both parts

---

## Summary

The query classification system adds an intelligent routing layer that:

✅ Improves response time by 75-80% for greetings/general queries  
✅ Reduces unnecessary document retrieval  
✅ Enhances user experience with instant casual responses  
✅ Maintains full RAG capabilities for document queries  
✅ Scales efficiently with minimal overhead  

**Result**: A smarter, faster, more user-friendly RAG assistant! 🚀

