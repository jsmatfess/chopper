<script setup>
import { onMounted, onUnmounted, ref } from 'vue';

const choices = { rust: 'Rust', python: 'Python' };
const preference = 'chopper-docs-library-language';
const picker = ref(null);
const selection = ref('');
let guide;

function applyLanguage(language) {
  selection.value = language;
  guide.dataset.libraryLanguage = language;
}

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
  applyLanguage(linked ?? (Object.hasOwn(choices, saved) ? saved : selection.value || 'rust'));
}

function chooseLanguage(language) {
  const url = new URL(window.location.href);
  url.searchParams.set('lang', language);
  window.history.replaceState(window.history.state, '', url);
  restoreLanguage();
}

onMounted(() => {
  guide = picker.value.closest('.vp-doc');
  restoreLanguage();
  window.addEventListener('popstate', restoreLanguage);
  window.addEventListener('hashchange', restoreLanguage);
});

onUnmounted(() => {
  delete guide.dataset.libraryLanguage;
  window.removeEventListener('popstate', restoreLanguage);
  window.removeEventListener('hashchange', restoreLanguage);
});
</script>

<template>
  <fieldset ref="picker" class="library-language" :hidden="!selection">
    <legend>Example language</legend>
    <div class="library-language-choices">
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
.library-language {
  margin-block-start: 1.5rem;
}

.library-language legend {
  font-weight: 650;
}

.library-language-choices {
  display: flex;
  flex-wrap: wrap;
  gap: 0 1rem;
}

.library-language-choices > div {
  display: flex;
  align-items: center;
  gap: .5rem;
}

.library-language input {
  accent-color: var(--vp-c-brand-1);
}

.library-language input:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

.library-language label {
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
</style>
