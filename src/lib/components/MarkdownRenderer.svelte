<script lang="ts">
  import { browser } from '$app/environment';
  import { onMount } from 'svelte';
  import { marked } from 'marked';
  
  export let content: string = '';
  export let className: string = '';
  
  let renderedHtml: string = '';
  let DOMPurify: any = null;
  
  // Configure marked options for better rendering
  marked.setOptions({
    breaks: true, // Convert line breaks to <br>
    gfm: true, // GitHub Flavored Markdown
    headerIds: false, // Disable header IDs for cleaner output
    mangle: false // Don't mangle email addresses
  });
  
  // Load DOMPurify only on client side (SSR-safe)
  onMount(async () => {
    if (typeof window !== 'undefined') {
      DOMPurify = (await import('dompurify')).default;
      renderMarkdown();
    }
  });
  
  function renderMarkdown() {
    if (!content) {
      renderedHtml = '';
      return;
    }
    
    try {
      // Convert markdown to HTML
      const html = marked.parse(content);
      
      // Sanitize HTML to prevent XSS attacks (only on client)
      if (DOMPurify && typeof window !== 'undefined') {
        renderedHtml = DOMPurify.sanitize(html, {
          ALLOWED_TAGS: [
            'p', 'br', 'strong', 'em', 'u', 's', 'code', 'pre',
            'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'blockquote', 'a', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td'
          ],
          ALLOWED_ATTR: ['href', 'title', 'target', 'rel']
        });
      } else {
        // SSR fallback: use marked output (will be sanitized on client hydration)
        renderedHtml = html;
      }
    } catch (error) {
      console.error('Markdown rendering error:', error);
      // Fallback to plain text if markdown parsing fails
      if (DOMPurify && typeof window !== 'undefined') {
        renderedHtml = DOMPurify.sanitize(content.replace(/\n/g, '<br>'));
      } else {
        renderedHtml = content.replace(/\n/g, '<br>');
      }
    }
  }
  
  // Re-render when content changes
  $: {
    if (typeof window !== 'undefined' && DOMPurify) {
      renderMarkdown();
    } else if (browser) {
      // Client-side but DOMPurify not loaded yet - render without sanitization
      // (will be re-rendered when DOMPurify loads)
      try {
        renderedHtml = marked.parse(content || '');
      } catch {
        renderedHtml = content || '';
      }
    } else {
      // SSR: render without sanitization (will be sanitized on client hydration)
      try {
        renderedHtml = marked.parse(content || '');
      } catch {
        renderedHtml = content || '';
      }
    }
  }
</script>

<div 
  bind:this={container}
  class="markdown-content {className}"
  data-content={content}
>
  {@html renderedHtml}
</div>

<style>
  :global(.markdown-content) {
    line-height: 1.6;
  }
  
  /* Inherit text color from parent (works for both user and AI messages) */
  :global(.markdown-content),
  :global(.markdown-content *) {
    color: inherit;
  }
  
  /* Paragraphs */
  :global(.markdown-content p) {
    @apply mb-3;
  }
  
  :global(.markdown-content p:last-child) {
    @apply mb-0;
  }
  
  /* Headings */
  :global(.markdown-content h1) {
    @apply text-2xl font-bold mt-6 mb-4;
  }
  
  :global(.markdown-content h2) {
    @apply text-xl font-bold mt-5 mb-3;
  }
  
  :global(.markdown-content h3) {
    @apply text-lg font-semibold mt-4 mb-2;
  }
  
  :global(.markdown-content h4) {
    @apply text-base font-semibold mt-3 mb-2;
  }
  
  :global(.markdown-content h5) {
    @apply text-sm font-semibold mt-2 mb-1;
  }
  
  :global(.markdown-content h6) {
    @apply text-xs font-semibold mt-2 mb-1;
  }
  
  /* Lists */
  :global(.markdown-content ul),
  :global(.markdown-content ol) {
    @apply mb-3 ml-6;
  }
  
  :global(.markdown-content ul) {
    @apply list-disc;
  }
  
  :global(.markdown-content ol) {
    @apply list-decimal;
  }
  
  :global(.markdown-content li) {
    @apply mb-1;
  }
  
  :global(.markdown-content li > p) {
    @apply mb-1;
  }
  
  /* Code */
  :global(.markdown-content code) {
    @apply px-1.5 py-0.5 rounded text-sm font-mono;
    background-color: rgba(0, 0, 0, 0.1);
  }
  
  :global(.markdown-content pre) {
    @apply p-4 rounded-lg overflow-x-auto mb-3;
    background-color: rgba(0, 0, 0, 0.1);
  }
  
  :global(.markdown-content pre code) {
    @apply bg-transparent p-0;
    background-color: transparent;
  }
  
  /* Blockquotes */
  :global(.markdown-content blockquote) {
    @apply border-l-4 pl-4 italic my-3;
    border-color: rgba(0, 0, 0, 0.2);
    opacity: 0.8;
  }
  
  /* Links - blue for AI messages (gray background) */
  :global(.markdown-content a) {
    @apply text-blue-600 hover:text-blue-800 underline;
  }
  
  /* Strong and Emphasis */
  :global(.markdown-content strong) {
    @apply font-semibold;
  }
  
  :global(.markdown-content em) {
    @apply italic;
  }
  
  /* Horizontal Rule */
  :global(.markdown-content hr) {
    @apply border-t border-gray-300 my-4;
  }
  
  /* Tables */
  :global(.markdown-content table) {
    @apply w-full border-collapse mb-3;
  }
  
  :global(.markdown-content th),
  :global(.markdown-content td) {
    @apply border border-gray-300 px-3 py-2;
  }
  
  :global(.markdown-content th) {
    @apply bg-gray-100 font-semibold;
  }
  
  :global(.markdown-content tr:nth-child(even)) {
    @apply bg-gray-50;
  }
</style>

