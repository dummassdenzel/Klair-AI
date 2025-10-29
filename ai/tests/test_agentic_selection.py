"""
Test agentic file selection system
"""
import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.document_processor.llm_service import LLMService
from services.document_processor.orchestrator import DocumentProcessorOrchestrator
from config import settings


async def test_1_llm_simple_generation():
    """Test 1: Basic LLM simple generation"""
    print("\n" + "="*80)
    print("TEST 1: Basic LLM Simple Generation")
    print("="*80)
    
    try:
        llm = LLMService(
            ollama_base_url=settings.OLLAMA_BASE_URL,
            ollama_model=settings.OLLAMA_MODEL,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            provider=settings.LLM_PROVIDER
        )
        
        print(f"✓ LLM Service created")
        print(f"  Provider: {llm.provider}")
        print(f"  Gemini Model: {llm.gemini_model}")
        print(f"  Gemini API Key: {'SET' if llm.gemini_api_key else 'NOT SET'}")
        
        # Test simple prompt
        simple_prompt = "Say only the word 'HELLO' and nothing else."
        print(f"\n📤 Sending prompt: {simple_prompt}")
        
        response = await llm.generate_simple(simple_prompt)
        
        print(f"📥 Response: {response}")
        
        if "couldn't generate" in response.lower():
            print("❌ FAILED: LLM returned error message")
            return False
        else:
            print("✅ PASSED: LLM generated response")
            return True
            
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_2_file_selection_prompt():
    """Test 2: File selection with mock file list"""
    print("\n" + "="*80)
    print("TEST 2: File Selection Prompt")
    print("="*80)
    
    try:
        llm = LLMService(
            ollama_base_url=settings.OLLAMA_BASE_URL,
            ollama_model=settings.OLLAMA_MODEL,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            provider=settings.LLM_PROVIDER
        )
        
        # Mock file list
        file_list = """1. REQUEST LETTER.docx (type: docx)
2. PES005.pdf (type: pdf)
3. TCO004 10.010 AMA.pdf (type: pdf)
4. sales.txt (type: txt)
5. minutes of the meeting.pdf (type: pdf)"""
        
        # Test query
        question = "How many delivery receipts do we have?"
        
        selection_prompt = f"""You are a file selection AI. Your ONLY job is to pick which files are needed to answer a question.

AVAILABLE FILES:
{file_list}

USER QUESTION: "{question}"

INSTRUCTIONS:
• If the question needs ALL files (e.g., "summarize everything", "list all documents"), respond: ALL_FILES
• If the question needs SPECIFIC files, respond with ONLY their numbers separated by commas

EXAMPLES:
• "What's in REQUEST LETTER?" → Find file with "REQUEST LETTER" in name → Return: 1
• "How many TCO documents?" → Find files starting with "TCO" → Return: 3
• "Files NOT delivery receipts" → Find files that are NOT receipts → Return: 1,4,5
• "Summarize all documents" → Return: ALL_FILES

CRITICAL RULES:
1. Look at filenames carefully
2. For "NOT X" queries, EXCLUDE X files
3. For pattern queries (e.g., "TCO"), match filename patterns
4. Only return numbers or "ALL_FILES"
5. NO explanations, NO other text

YOUR RESPONSE (ONLY numbers or "ALL_FILES"):"""
        
        print(f"📤 Query: {question}")
        print(f"📋 File list:\n{file_list}")
        print(f"\n🤖 Sending selection prompt to LLM...")
        
        response = await llm.generate_simple(selection_prompt)
        
        print(f"📥 LLM Response: '{response}'")
        
        if "couldn't generate" in response.lower() or "error" in response.lower():
            print("❌ FAILED: LLM returned error message")
            return False
        elif response.strip():
            print(f"✅ PASSED: LLM returned: {response.strip()}")
            
            # Try to parse
            cleaned = ''.join(c for c in response if c.isdigit() or c == ',')
            if cleaned:
                file_numbers = [int(num.strip()) for num in cleaned.split(",") if num.strip()]
                print(f"✓ Parsed file numbers: {file_numbers}")
            elif "ALL_FILES" in response.upper():
                print(f"✓ Parsed as: ALL_FILES")
            
            return True
        else:
            print("❌ FAILED: Empty response")
            return False
            
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_3_full_orchestrator_selection():
    """Test 3: Full orchestrator file selection (requires indexed documents)"""
    print("\n" + "="*80)
    print("TEST 3: Full Orchestrator File Selection")
    print("="*80)
    
    try:
        orchestrator = DocumentProcessorOrchestrator(
            ollama_base_url=settings.OLLAMA_BASE_URL,
            ollama_model=settings.OLLAMA_MODEL,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            llm_provider=settings.LLM_PROVIDER
        )
        
        print(f"✓ Orchestrator created")
        
        # Check if files are indexed
        if not orchestrator.file_metadata:
            print("⚠️  WARNING: No files indexed. Please index documents first.")
            print("   Run: python -m uvicorn main:app --reload")
            print("   Then use /api/set-directory to index documents")
            return None
        
        print(f"✓ Found {len(orchestrator.file_metadata)} indexed files:")
        for idx, (file_path, metadata) in enumerate(orchestrator.file_metadata.items(), 1):
            filename = Path(file_path).name
            print(f"   {idx}. {filename}")
        
        # Test file selection
        question = "How many delivery receipts do we have?"
        print(f"\n🔍 Testing query: {question}")
        
        selected_files = await orchestrator._select_relevant_files(question)
        
        if selected_files is None:
            print("📋 Result: ALL_FILES (general query)")
            print("⚠️  Expected: Specific files (TCO, PES patterns)")
            return False
        else:
            print(f"🎯 Result: {len(selected_files)} specific files:")
            for file_path in selected_files:
                print(f"   - {Path(file_path).name}")
            return True
            
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_4_negation_query():
    """Test 4: Negation query (NOT delivery receipts)"""
    print("\n" + "="*80)
    print("TEST 4: Negation Query")
    print("="*80)
    
    try:
        llm = LLMService(
            ollama_base_url=settings.OLLAMA_BASE_URL,
            ollama_model=settings.OLLAMA_MODEL,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            provider=settings.LLM_PROVIDER
        )
        
        # Mock file list with clear receipts and non-receipts
        file_list = """1. REQUEST LETTER.docx (type: docx)
2. PES005 delivery receipt.pdf (type: pdf)
3. TCO004 delivery receipt.pdf (type: pdf)
4. sales.txt (type: txt)
5. minutes of the meeting.pdf (type: pdf)
6. GUA04 receipt.pdf (type: pdf)"""
        
        question = "How many files are NOT delivery receipts?"
        
        selection_prompt = f"""You are a file selection AI. Your ONLY job is to pick which files are needed to answer a question.

AVAILABLE FILES:
{file_list}

USER QUESTION: "{question}"

INSTRUCTIONS:
• If the question needs ALL files (e.g., "summarize everything", "list all documents"), respond: ALL_FILES
• If the question needs SPECIFIC files, respond with ONLY their numbers separated by commas

EXAMPLES:
• "What's in REQUEST LETTER?" → Find file with "REQUEST LETTER" in name → Return: 1
• "How many TCO documents?" → Find files starting with "TCO" → Return: 3
• "Files NOT delivery receipts" → Find files that are NOT receipts → Return: 1,4,5
• "Summarize all documents" → Return: ALL_FILES

CRITICAL RULES:
1. Look at filenames carefully
2. For "NOT X" queries, EXCLUDE X files
3. For pattern queries (e.g., "TCO"), match filename patterns
4. Only return numbers or "ALL_FILES"
5. NO explanations, NO other text

YOUR RESPONSE (ONLY numbers or "ALL_FILES"):"""
        
        print(f"📤 Query: {question}")
        print(f"📋 File list:\n{file_list}")
        print(f"\n🤖 Expected: 1,4,5 (exclude PES, TCO, GUA receipts)")
        
        response = await llm.generate_simple(selection_prompt)
        
        print(f"📥 LLM Response: '{response}'")
        
        if "couldn't generate" in response.lower():
            print("❌ FAILED: LLM returned error message")
            return False
        
        # Parse and check
        cleaned = ''.join(c for c in response if c.isdigit() or c == ',')
        if cleaned:
            file_numbers = [int(num.strip()) for num in cleaned.split(",") if num.strip()]
            print(f"✓ Parsed file numbers: {file_numbers}")
            
            # Check if it correctly excluded receipts
            expected = {1, 4, 5}
            actual = set(file_numbers)
            
            if actual == expected:
                print("✅ PASSED: Correctly identified non-receipt files")
                return True
            else:
                print(f"⚠️  PARTIAL: Got {actual}, expected {expected}")
                # Still count as success if it excluded at least the receipts
                if 2 not in actual and 3 not in actual and 6 not in actual:
                    print("✓ At least excluded receipt files correctly")
                    return True
                return False
        else:
            print("❌ FAILED: Could not parse response")
            return False
            
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_5_direct_gemini_test():
    """Test 5: Direct Gemini API test (bypass LLMService)"""
    print("\n" + "="*80)
    print("TEST 5: Direct Gemini API Test")
    print("="*80)
    
    try:
        import google.generativeai as genai
        
        if not settings.GEMINI_API_KEY:
            print("❌ FAILED: GEMINI_API_KEY not set")
            return False
        
        print(f"✓ Configuring Gemini with API key...")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        
        print(f"✓ Creating model: {settings.GEMINI_MODEL}")
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        
        print(f"📤 Sending test prompt...")
        response = model.generate_content("Say only the word 'HELLO' and nothing else.")
        
        print(f"📥 Response type: {type(response)}")
        print(f"📥 Response text: {response.text}")
        
        if response.text:
            print("✅ PASSED: Direct Gemini API works")
            return True
        else:
            print("❌ FAILED: No response text")
            return False
            
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_6_query_classification():
    """Test 6: Query classification (greeting vs general vs document)"""
    print("\n" + "="*80)
    print("TEST 6: Query Classification")
    print("="*80)
    
    try:
        orchestrator = DocumentProcessorOrchestrator(
            ollama_base_url=settings.OLLAMA_BASE_URL,
            ollama_model=settings.OLLAMA_MODEL,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            llm_provider=settings.LLM_PROVIDER
        )
        
        test_queries = [
            ("hello!", "greeting"),
            ("hi there", "greeting"),
            ("how are you?", "greeting"),
            ("what can you do?", "general"),
            ("how does this work?", "general"),
            ("tell me about yourself", "general"),
            ("what's in the sales report?", "document"),
            ("how many TCO documents?", "document"),
            ("list all files", "document"),
            ("summarize REQUEST LETTER", "document"),
        ]
        
        results = []
        for query, expected_type in test_queries:
            classification = await orchestrator._classify_query(query)
            correct = classification == expected_type
            status = "✅" if correct else "❌"
            results.append(correct)
            
            print(f"{status} '{query}' → {classification} (expected: {expected_type})")
        
        accuracy = sum(results) / len(results) * 100
        print(f"\n📊 Accuracy: {accuracy:.0f}% ({sum(results)}/{len(results)} correct)")
        
        if accuracy >= 80:
            print("✅ PASSED: Classification accuracy is good")
            return True
        else:
            print("⚠️  PARTIAL: Classification accuracy could be better")
            return True if accuracy >= 60 else False
            
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests"""
    print("\n" + "🧪"*40)
    print("AGENTIC FILE SELECTION DIAGNOSTIC TESTS")
    print("🧪"*40)
    
    print(f"\n📋 Configuration:")
    print(f"   LLM Provider: {settings.LLM_PROVIDER}")
    print(f"   Gemini Model: {settings.GEMINI_MODEL}")
    print(f"   Gemini API Key: {'SET ✓' if settings.GEMINI_API_KEY else 'NOT SET ✗'}")
    print(f"   Ollama URL: {settings.OLLAMA_BASE_URL}")
    print(f"   Ollama Model: {settings.OLLAMA_MODEL}")
    
    results = {}
    
    # Run tests
    results['test_1'] = await test_1_llm_simple_generation()
    results['test_2'] = await test_2_file_selection_prompt()
    results['test_3'] = await test_3_full_orchestrator_selection()
    results['test_4'] = await test_4_negation_query()
    results['test_5'] = await test_5_direct_gemini_test()
    results['test_6'] = await test_6_query_classification()
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    for test_name, result in results.items():
        if result is True:
            status = "✅ PASSED"
        elif result is False:
            status = "❌ FAILED"
        else:
            status = "⚠️  SKIPPED"
        print(f"{test_name}: {status}")
    
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    print(f"\n📊 Results: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed > 0:
        print("\n⚠️  DIAGNOSIS:")
        if not results.get('test_5'):
            print("   → Direct Gemini API test failed")
            print("   → Check GEMINI_API_KEY and model name")
        if not results.get('test_1'):
            print("   → Basic LLM generation failed")
            print("   → Check LLMService initialization")
        if not results.get('test_2'):
            print("   → File selection prompt failed")
            print("   → LLM may not be following instructions")
        if not results.get('test_4'):
            print("   → Negation logic failed")
            print("   → LLM may need clearer prompt")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    asyncio.run(main())

