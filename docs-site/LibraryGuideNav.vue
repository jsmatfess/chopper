<script setup>
import { onMounted, onUnmounted, ref } from 'vue';

const props = defineProps({
  base: { type: String, required: true },
  current: { type: String, default: '' },
});
const guides = { rust: 'Rust', python: 'Python' };
const fragment = ref('');

function updateSection() {
  if (!props.current) return;
  fragment.value = '';
  let id;
  try {
    id = decodeURIComponent(window.location.hash.slice(1));
  } catch {
    return;
  }
  const section = document.getElementById(id);
  if (section?.matches('.vp-doc h2, .vp-doc h3')) fragment.value = window.location.hash;
}

onMounted(() => {
  updateSection();
  window.addEventListener('hashchange', updateSection);
});
onUnmounted(() => window.removeEventListener('hashchange', updateSection));
</script>

<template>
  <nav aria-label="Library guides" class="library-guide-links">
    <a
      v-for="(label, language) in guides"
      :key="language"
      :href="base + 'libraries-' + language + fragment"
      :aria-current="current === language ? 'page' : undefined"
    >{{ label }}</a>
  </nav>
</template>
