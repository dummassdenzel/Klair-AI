# Metadata-First Indexing: User Flow

## New Application Flow

### Before (Old Flow)
1. User selects directory
2. **Wait 10-30 seconds** for full indexing
3. Chat is blocked until indexing completes
4. User can finally query documents

### After (New Flow with Metadata-First Indexing)
1. User selects directory
2. **Metadata indexed in < 1 second** ✅
3. **Chat is immediately available** for filename/metadata queries
4. Content indexing happens in background (non-blocking)
5. Full content queries work once background indexing completes

## Step-by-Step User Experience

### Step 1: Directory Selection
- User clicks "Select Directory"
- Backend receives directory path
- **Backend immediately starts metadata indexing** (< 1 second)

### Step 2: Immediate Availability (< 1 second)
- **Frontend shows**: "Metadata indexed ✅"
- **Chat input is enabled** immediately
- **User can query**:
  - "list all files"
  - "show me PDF files"
  - "what files are in this directory?"
  - Filename-based queries

### Step 3: Background Content Indexing
- **Frontend shows**: "Content indexing in progress..." (non-blocking)
- **User can still query** files by name
- Content indexing happens in background
- Progress updates every 3 seconds

### Step 4: Full Content Queries Available
- Once content indexing completes:
  - "What's in [filename]?"
  - "Summarize the documents"
  - "Find information about [topic]"
- All queries work with full content

## Frontend Changes

### New State Management
- `metadataIndexed`: Boolean - true when metadata is indexed
- `contentIndexingInProgress`: Boolean - true when content is being indexed
- `isIndexingInProgress`: Boolean - true only during initial metadata indexing

### UI Updates

#### Chat Input
- **Before metadata indexed**: Disabled, shows "Indexing metadata..."
- **After metadata indexed**: Enabled, shows "Ask about files by name..."
- **During content indexing**: Enabled, shows helpful message about background indexing

#### Status Messages
- **Blue banner** (blocking): "Indexing document metadata..." - appears only during initial metadata indexing
- **Amber banner** (non-blocking): "Content indexing in progress..." - appears during background content indexing
- **No banner**: All indexing complete

#### Document List
- Shows all documents immediately after metadata indexing
- Documents with `processing_status: "metadata_only"` show "Indexing..." indicator
- Documents with `processing_status: "indexed"` show full content preview

## Backend Flow

### Phase 1: Metadata Indexing (< 1 second)
```python
# Fast metadata scan
for file_path in directory:
    # Extract: filename, size, type, modified date
    # Store in database with status="metadata_only"
    # NO content reading, NO hashing, NO embeddings
```

### Phase 2: Background Content Indexing
```python
# Background task (non-blocking)
for file_path in metadata_files:
    # Extract text content
    # Create chunks
    # Generate embeddings
    # Update database status="indexed"
```

## API Response Changes

### Directory Selection Response
```json
{
  "status": "success",
  "message": "Directory set successfully. Documents are being processed in the background.",
  "directory": "/path/to/directory",
  "processing_status": "background_processing"
}
```

### Document Status
Documents now have `processing_status` field:
- `"metadata_only"`: Metadata indexed, content indexing in progress
- `"indexed"`: Fully indexed, ready for content queries
- `"error"`: Failed to index

## Benefits for Users

1. **Instant Availability**: Query files immediately (< 1 second)
2. **No Blocking**: Can use app while content indexes
3. **Better UX**: Clear status indicators
4. **Progressive Enhancement**: More features available as indexing completes

## Testing the Flow

1. **Select a directory** with 10-50 files
2. **Immediately try**: "list all files" (should work in < 1 second)
3. **Wait 10-30 seconds**, then try: "What's in [filename]?" (should work after content indexing)
4. **Check sidebar**: Documents should show indexing status

## Troubleshooting

### Chat not available immediately
- Check if `metadataIndexed` is set to true
- Verify backend completed metadata indexing
- Check browser console for errors

### Content queries not working
- Wait for content indexing to complete (check status in sidebar)
- Verify documents have `processing_status: "indexed"`
- Check backend logs for indexing errors

### Status not updating
- Check if refresh interval is running (every 3 seconds)
- Verify API calls to `/documents/search` are working
- Check network tab for API responses

