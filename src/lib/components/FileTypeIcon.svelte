<script lang="ts">
  import { getFileTypeConfig } from '$lib/utils/fileTypes';

  const FALLBACK_ICON = 'document';

  let {
    fileType = '',
    class: className = 'w-4 h-4 flex-shrink-0',
    ariaLabel = 'File type icon'
  } = $props<{
    fileType: string;
    class?: string;
    ariaLabel?: string;
  }>();

  const config = $derived(getFileTypeConfig(fileType));
  const iconSrc = $derived(`/icons/vscode-material/${config.iconName}.svg`);
  let currentSrc = $state('');

  $effect(() => {
    currentSrc = iconSrc;
  });

  function onError() {
    if (currentSrc.endsWith(`${FALLBACK_ICON}.svg`)) return;
    currentSrc = `/icons/vscode-material/${FALLBACK_ICON}.svg`;
  }

  const displaySrc = $derived(currentSrc || iconSrc);
</script>

<img
  src={displaySrc}
  alt={ariaLabel}
  class={className}
  loading="lazy"
  onerror={onError}
/>
