# AI Assistant System Architecture Review & Development Roadmap

## 1. Purpose of This Document

This document describes the **current architecture, capabilities, strengths, weaknesses, and required improvements** of the AI document assistant system.

It is designed to give **developers, future contributors, and AI IDE assistants** a complete understanding of:

• What the system currently does
• How it is architected
• Which parts are working well
• Which parts are fragile or incorrect
• What must remain unchanged
• What must be redesigned for long-term scalability

The goal is to evolve the system into a **natural conversational assistant for document collections**, similar in usability to modern AI assistants such as ChatGPT, Claude, or Cursor, while maintaining strong document grounding.

---

# 2. System Goals

The system is intended to be a **folder-scoped AI assistant** capable of:

• Conversational interaction with users
• Question answering over document collections
• Multi-document reasoning
• Aggregations across documents
• Document discovery and explanation
• Follow-up questions using conversational context

The assistant must remain:

• Grounded in document content
• Fast enough for interactive usage (target: 1–7 seconds)
• Domain agnostic (works for many document types)

---

# 3. High-Level System Architecture

Current pipeline:

User Query
↓
Intent Classifier / Router
↓
Select Query Path
• Greeting
• Document Listing
• Document Search
• Aggregation
↓
Hybrid Retrieval (Chroma + BM25)
↓
Optional Cross-Encoder Reranking
↓
Construct RAG Context
↓
LLM Response Generation
↓
Streaming or Final Output

---

# 4. Current Technology Stack

## LLM

Model: `meta-llama/llama-4-scout-17b-16e-instruct`
Provider: Groq (primary), with optional Ollama and Gemini support.

### Output Limits

Max response tokens: 8192

### Input Limits

Groq: ~50k characters context
Other providers: effectively unlimited.

---

## Vector Database

ChromaDB

Per-tenant persistent directories.

Used for:
• semantic retrieval
• metadata filtering

---

## Keyword Search

BM25 index stored alongside vector store.

Purpose:
• lexical search
• retrieval of IDs and numeric values

---

## Embeddings

Model:

BAAI/bge-small-en-v1.5

Used for:
• vector similarity search
• hybrid retrieval

---

## Retrieval Strategy

Hybrid retrieval:

vector search
+
BM25 keyword search
+
Reciprocal Rank Fusion (RRF)

Optional reranking using:

ms-marco-MiniLM-L-6-v2 cross-encoder

---

# 5. Chunking Strategy

Current configuration:

Chunk size: 1000 characters
Chunk overlap: 200 characters

Advantages:

• Simple
• Works well for unstructured text
• Easy to tune

Limitations:

• Splits structured content (tables, invoices)
• Breaks logical document boundaries
• Weak for forms and semi-structured data

Future improvement: semantic chunking.

---

# 6. Retrieval Parameters

After reranking, the system sends a final number of chunks to the LLM.

| Query type            | Chunks sent               |
| --------------------- | ------------------------- |
| General search        | 20                        |
| Aggregation queries   | 50                        |
| Specific file queries | 15                        |
| General fallback      | 10                        |
| Document listing      | separate listing pipeline |

Distinct source limits are also applied.

This prevents:

• context overload
• excessive document diversity

---

# 7. Metadata Stored on Chunks

Current metadata fields:

file_path
file_type
chunk_id
document_category

Derived fields:

filename (from file_path)

### Missing Metadata

The system currently does NOT store:

page number
section
table boundaries
dates
author information

This limits citation accuracy.

---

# 8. Filename Index

The system maintains a **FilenameTrie**.

Purpose:

• detect explicit filename references
• autocomplete filenames
• match document identifiers

Example matches:

BIP-12046
BIP-12046.pdf

This solves a common RAG weakness where embeddings fail to match document IDs.

This component is **correct and must remain**.

---

# 9. Conversation Memory

The system stores:

chat sessions
messages
recent conversation history

Conversation history is used for:

• intent classification
• resolving references (them, those, it)
• LLM prompt context

This allows follow-up questions.

Example:

User: explain BIP-12046
User: when was it delivered

However, explicit **entity tracking is not yet implemented**.

---

# 10. Streaming

Two API modes exist:

Non-streaming:
POST /api/chat

Streaming (SSE):
POST /api/chat/stream

Streaming sends:

meta
token events
done

Streaming significantly improves perceived latency.

This system should remain.

---

# 11. Document Types Supported

Supported file types:

PDF
DOCX
TXT
XLSX
XLS
PPTX
Images (OCR)

The system is domain agnostic.

Documents may be:

Unstructured
• reports
• text documents

Semi-structured
• invoices
• receipts
• forms

Structured
• spreadsheets

However the system currently **treats all documents identically** during chunking and retrieval.

---

# 12. What the System Does Well

The following parts of the system are strong and should remain unchanged.

### Hybrid Retrieval

Combining vector search and BM25 significantly improves recall.

### Cross-Encoder Reranking

Improves relevance of retrieved chunks.

### Filename Detection

Critical for document identifier matching.

### Conversation History

Allows contextual follow-ups.

### Streaming Responses

Improves user experience.

### Metadata Filtering

Supports queries like:

total value of invoices

### Hybrid Retrieval Pipeline

Overall retrieval architecture is production quality.

---

# 13. Weaknesses in the Current Architecture

The main weakness is **query routing design**.

The system currently relies heavily on:

pattern matching
regex classification
rule based routing

This causes several problems.

---

## Problem 1: Intent Rigidity

The classifier must choose **one intent** before the LLM runs.

But user queries often contain **multiple intents**.

Example:

what invoices do we have and what is the total value

This requires both:

listing
aggregation

The current architecture struggles with this.

---

## Problem 2: Intent Rule Explosion

As the system grows, developers will add more patterns:

explain our files
what kind of files
describe the documents

This leads to hundreds of brittle rules.

---

## Problem 3: Over-Reliance on Routing

The system decides behavior using rules instead of letting the model reason.

Modern AI assistants allow the model to choose actions.

---

## Problem 4: Weak Corpus Understanding

The assistant understands **chunks**, but not the **dataset as a whole**.

Queries like:

what documents are here
what kind of files do we have

should use corpus understanding, not chunk retrieval.

---

## Problem 5: Missing Document Structure

Chunks do not store:

page numbers
sections
tables

This prevents precise citations.

---

# 14. What Must Remain

These components are correct and should remain unchanged.

Hybrid retrieval pipeline
FilenameTrie identifier detection
Conversation history storage
Streaming infrastructure
Cross-encoder reranking
Metadata filtering system

These form a strong foundation.

---

# 15. What Must Be Improved

## Query Rewriting

Follow-up questions must be rewritten before retrieval.

Example:

User: when was that delivered
Rewrite: when was BIP-12046 delivered

This improves retrieval accuracy.

---

## Entity Tracking

The system should track entities referenced during conversation.

Example entity:

BIP-12046.pdf

Follow-ups can reference it automatically.

---

## Corpus Summary

During indexing, generate a **folder summary**.

Example:

This folder contains 320 logistics documents including delivery notes, invoices, and export declarations.

Queries about the dataset can then be answered instantly.

---

## Planner Layer

Replace rule based routing with an LLM planning step.

Example output:

intent: aggregation
category: invoices
also_list_documents: true

This allows the assistant to handle multi-intent queries.

---

## Document Structure Metadata

Add metadata fields:

page
section
table
date

This enables better citations.

---

## Structured Document Handling

Invoices and tables should use specialized parsing and chunking.

---

# 16. Long-Term Architecture Direction

The system should gradually move from:

rule driven routing

toward:

LLM assisted planning.

Future pipeline:

User Query
↓
Planner LLM decides actions
↓
System executes tools
• search_documents
• list_documents
• aggregate_documents
↓
LLM composes final answer

This allows the assistant to behave more like modern AI assistants.

---

# 17. Target System Characteristics

The final assistant should be able to:

Understand vague user questions
Handle conversational follow-ups
Combine multiple document queries
Explain datasets
Reference documents precisely
Operate quickly within the 1–7 second target

---

# 18. Summary

Current state:

Strong retrieval engine
Early assistant architecture

Strengths:

Hybrid RAG
Reranking
Filename detection
Streaming
Conversation history

Weaknesses:

Rule based routing
Limited corpus understanding
Missing document structure metadata

Next major priorities:

Query rewriting
Entity tracking
Corpus summaries
Planner based architecture

With these improvements, the system can evolve into a **robust conversational document intelligence platform**.
