# PPTX Preview Implementation Plan

## Current State Analysis

### ✅ What's Working
1. **Backend Text Extraction**: PPTX text extraction is fully functional (`text_extractor.py`)
2. **Backend File Serving**: PPTX files are served correctly via `/api/documents/{document_id}/file`
3. **AI Awareness**: RAG system can query and understand PPTX content

### ❌ What's Missing
1. **Client-side Preview**: `DocumentViewer.svelte` throws "Unsupported file type" for PPTX
2. **No Conversion Service**: No server-side conversion from PPTX to viewable format

## Recommended Solution: Server-Side PDF Conversion

### Why This Approach?
1. **Reuses Existing Infrastructure**: Client already has PDF.js for rendering
2. **High Quality**: LibreOffice provides excellent conversion quality
3. **Consistent UX**: Same rendering pipeline as PDF files
4. **Reliable**: LibreOffice handles complex PPTX files better than client-side libraries
5. **Performance**: Server-side processing doesn't burden client devices

### Architecture Overview

```
┌─────────────┐
│   Client    │
│  (Svelte)   │
└──────┬──────┘
       │ 1. Request PPTX preview
       ▼
┌─────────────────────────────────┐
│   FastAPI Backend               │
│                                 │
│  ┌──────────────────────────┐  │
│  │  /api/documents/{id}/    │  │
│  │  preview?format=pdf      │  │
│  └──────────┬───────────────┘  │
│             │                    │
│  ┌──────────▼──────────────┐   │
│  │  PPTX Converter Service │   │
│  │  (LibreOffice headless)  │   │
│  └──────────┬──────────────┘   │
│             │                    │
│  ┌──────────▼──────────────┐   │
│  │  Cache Layer            │   │
│  │  (File hash based)      │   │
│  └─────────────────────────┘   │
└─────────────────────────────────┘
       │ 2. Convert PPTX → PDF
       │ 3. Return PDF stream
       ▼
┌─────────────┐
│   Client    │
│  (PDF.js)   │
└─────────────┘
```

## Implementation Steps

### Phase 1: Backend - PPTX Converter Service

#### 1.1 Create Converter Service
**File**: `ai/services/document_processor/extraction/pptx_converter.py`

**Responsibilities**:
- Convert PPTX to PDF using LibreOffice headless
- Handle conversion errors gracefully
- Support caching to avoid re-conversion
- Clean up temporary files

**Key Functions**:
```python
async def convert_pptx_to_pdf(pptx_path: str, output_dir: str) -> str
async def get_cached_pdf(pptx_path: str, cache_dir: str) -> Optional[str]
```

#### 1.2 Add Configuration
**File**: `ai/config.py`

Add settings:
- `LIBREOFFICE_PATH`: Path to LibreOffice executable (auto-detect if not set)
- `PPTX_CACHE_DIR`: Directory for cached PDF conversions
- `PPTX_CACHE_ENABLED`: Enable/disable caching (default: True)

#### 1.3 Create Preview Endpoint
**File**: `ai/main.py`

**New Endpoint**: `/api/documents/{document_id}/preview`

**Query Parameters**:
- `format`: Requested format (default: "pdf")
- `force_refresh`: Bypass cache (default: false)

**Response**: PDF file stream with appropriate headers

### Phase 2: Frontend - PPTX Preview Support

#### 2.1 Update DocumentViewer Component
**File**: `src/lib/components/DocumentViewer.svelte`

**Changes**:
1. Add PPTX case to `loadDocument()` function
2. For PPTX files, request preview endpoint instead of file endpoint
3. Use existing `renderPDF()` function to display converted PDF

**Code Pattern**:
```typescript
if (fileType === 'pptx') {
  // Request preview endpoint (returns PDF)
  const response = await apiClient.get(`/documents/${doc.id}/preview?format=pdf`, {
    responseType: 'blob'
  });
  await renderPDF(response.data);
}
```

### Phase 3: Error Handling & Edge Cases

#### 3.1 Handle Conversion Failures
- Fallback to text-only preview if conversion fails
- Show user-friendly error messages
- Log conversion errors for debugging

#### 3.2 Handle Large Files
- Add timeout for conversion (e.g., 60 seconds)
- Show progress indicator for long conversions
- Consider async conversion with status polling for very large files

#### 3.3 Cache Management
- Cache invalidation when PPTX file changes (use file hash)
- Periodic cleanup of old cache files
- Configurable cache size limits

## Technical Details

### LibreOffice Headless Command

**Windows**:
```bash
"C:\Program Files\LibreOffice\program\soffice.exe" --headless --convert-to pdf --outdir "{output_dir}" "{pptx_path}"
```

**Linux/Mac**:
```bash
soffice --headless --convert-to pdf --outdir "{output_dir}" "{pptx_path}"
```

### Caching Strategy

**Cache Key**: SHA256 hash of PPTX file content
**Cache Location**: `{PPTX_CACHE_DIR}/{hash}.pdf`
**Cache Invalidation**: 
- Check file modification time
- Re-convert if source file is newer than cache

### Error Handling

**Common Issues**:
1. LibreOffice not found → Check PATH, provide helpful error
2. Conversion timeout → Return error, suggest file is too large
3. Corrupted PPTX → Return error, suggest re-saving file
4. Permission issues → Log error, return generic error to user

## Alternative Approaches Considered

### ❌ Client-Side JavaScript Libraries
- **Rejected**: Limited support for complex PPTX files, large bundle size, inconsistent rendering

### ❌ Convert to Images (PNG/JPEG)
- **Rejected**: Larger file sizes, multiple requests, more complex implementation

### ✅ Server-Side PDF Conversion
- **Selected**: Best balance of quality, performance, and maintainability

## Testing Strategy

### Unit Tests
1. Test converter service with various PPTX files
2. Test cache hit/miss scenarios
3. Test error handling (missing LibreOffice, corrupted files)

### Integration Tests
1. Test full flow: Request → Convert → Cache → Serve
2. Test concurrent requests for same file
3. Test cache invalidation on file update

### Manual Testing
1. Test with simple PPTX files
2. Test with complex PPTX files (animations, embedded media)
3. Test with large PPTX files (>50MB)
4. Test with corrupted/invalid PPTX files

## Performance Considerations

### Optimization Strategies
1. **Caching**: Avoid re-conversion of unchanged files
2. **Async Processing**: For very large files, consider background conversion
3. **Streaming**: Stream PDF as it's generated (if possible)
4. **Compression**: Compress PDF output if needed

### Expected Performance
- **Small PPTX (<5MB)**: < 2 seconds conversion
- **Medium PPTX (5-20MB)**: 2-5 seconds conversion
- **Large PPTX (>20MB)**: 5-15 seconds conversion
- **Cache Hit**: < 100ms (file read)

## Security Considerations

1. **Path Validation**: Ensure PPTX path is within allowed directories
2. **Temporary Files**: Secure cleanup of temporary files
3. **Cache Directory**: Restrict access to cache directory
4. **File Size Limits**: Enforce maximum file size for conversion

## Future Enhancements

1. **Slide-by-Slide Preview**: Convert individual slides to images for faster loading
2. **Thumbnail Generation**: Generate thumbnails for slide navigation
3. **Progressive Loading**: Load slides as user scrolls
4. **Alternative Formats**: Support HTML export for better web rendering

## Implementation Checklist

### Backend
- [ ] Create `pptx_converter.py` service
- [ ] Add LibreOffice path detection
- [ ] Add configuration settings
- [ ] Create preview endpoint
- [ ] Implement caching logic
- [ ] Add error handling
- [ ] Add logging
- [ ] Write unit tests

### Frontend
- [ ] Update `DocumentViewer.svelte` for PPTX
- [ ] Add loading states
- [ ] Add error handling UI
- [ ] Test with various PPTX files

### Documentation
- [ ] Update API documentation
- [ ] Add setup instructions for LibreOffice
- [ ] Document configuration options

## Dependencies

### New Python Dependencies
- None required (uses subprocess for LibreOffice)

### System Requirements
- LibreOffice installed and accessible in PATH
- Sufficient disk space for cache directory

## Estimated Effort

- **Backend Development**: 4-6 hours
- **Frontend Development**: 1-2 hours
- **Testing**: 2-3 hours
- **Documentation**: 1 hour
- **Total**: 8-12 hours

## Risk Assessment

### Low Risk
- ✅ LibreOffice is stable and widely used
- ✅ PDF rendering already works
- ✅ Conversion is stateless operation

### Medium Risk
- ⚠️ LibreOffice installation varies by OS
- ⚠️ Large files may timeout
- ⚠️ Complex PPTX files may not convert perfectly

### Mitigation
- Auto-detect LibreOffice path with fallbacks
- Add configurable timeouts
- Provide fallback text preview on conversion failure

