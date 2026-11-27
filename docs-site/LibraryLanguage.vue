<script setup>
import { onMounted, onUnmounted, ref } from 'vue';

const choices = { rust: 'Rust', python: 'Python' };
const preference = 'chopper-docs-library-language';
const picker = ref(null);
const selection = ref('');
let guide;
let anchorFrame;

function restoreLanguage() {
  const url = new URL(window.location.href);
  const linked = [url.searchParams.get('lang'), url.hash.slice(1)]
    .find(language => Object.hasOwn(choices, language));
  let saved;
  try {
    saved = window.localStorage.getItem(preference);
    if (linked) window.localStorage.setItem(preference, linked);
  } catch {
    // The URL still works when the browser blocks storage.
  }
  selection.value = linked ?? (Object.hasOwn(choices, saved) ? saved : selection.value || 'rust');
  guide.dataset.libraryLanguage = selection.value;
}

function chooseLanguage(language) {
  const url = new URL(window.location.href);
  url.searchParams.set('lang', language);
  window.history.replaceState(window.history.state, '', url);
  restoreLanguage();
}

function alignLinkedSection() {
  let id;
  try {
    id = decodeURIComponent(window.location.hash.slice(1));
  } catch {
    return;
  }
  const target = document.getElementById(id);
  if (target && guide.contains(target)) target.scrollIntoView({ block: 'start' });
}

onMounted(() => {
  guide = picker.value.closest('.vp-doc');
  restoreLanguage();
  // The initial fragment scroll can happen before the language changes the layout.
  if (window.location.hash && !window.history.state?.scrollPosition) {
    anchorFrame = window.requestAnimationFrame(alignLinkedSection);
  }
  window.addEventListener('popstate', restoreLanguage);
  window.addEventListener('hashchange', restoreLanguage);
});

onUnmounted(() => {
  window.cancelAnimationFrame(anchorFrame);
  delete guide.dataset.libraryLanguage;
  window.removeEventListener('popstate', restoreLanguage);
  window.removeEventListener('hashchange', restoreLanguage);
});
</script>

<template>
  <fieldset ref="picker" class="library-picker" :hidden="!selection">
    <legend>Example language</legend>
    <div class="library-picker-options">
      <div v-for="(label, language) in choices" :key="language">
        <input
          :id="`library-language-${language}`"
          type="radio"
          name="library-language"
          :value="language"
          :checked="selection === language"
          @change="chooseLanguage(language)"
        >
        <label :for="`library-language-${language}`">{{ label }}</label>
      </div>
    </div>
  </fieldset>
</template>

<style>
.library-picker {
  border: 0;
  margin-block-start: 1.5rem;
  min-inline-size: 0;
  padding: 0;
}

.library-picker legend {
  font-weight: 650;
}

.library-picker-options {
  display: flex;
  flex-wrap: wrap;
  gap: 0 1rem;
}

.library-picker-options > div {
  display: flex;
  align-items: center;
  gap: .5rem;
}

.library-picker input {
  accent-color: var(--vp-c-brand-1);
}

.library-picker input:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

.library-picker label {
  display: inline-flex;
  align-items: center;
  min-block-size: 3rem;
  min-inline-size: 3rem;
  cursor: pointer;
}

[data-library-language="rust"] [data-library-example="python"],
[data-library-language="python"] [data-library-example="rust"] {
  display: none;
}

[data-library-language] :is(h1, h2, h3, .library-section-alias) {
  scroll-margin-block-start: calc(var(--vp-nav-height) + 3.5rem);
}

.library-section-alias {
  display: block;
}
</style>
