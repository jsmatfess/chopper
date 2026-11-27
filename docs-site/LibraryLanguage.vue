<script setup>
import { onMounted, onUnmounted, ref } from 'vue';

const props = defineProps({ formulaReference: Boolean });
const choices = {
  ...(props.formulaReference ? { formula: 'Formula text' } : {}),
  rust: 'Rust',
  python: 'Python',
};
const pickerId = props.formulaReference ? 'formula-language' : 'library-language';
const preference = 'chopper-docs-library-language';
const picker = ref(null);
const selection = ref('');
let guide;
let anchorFrame;
let formulaPanels = [];

function restoreLanguage() {
  const url = new URL(window.location.href);
  if (props.formulaReference) {
    const linked = url.searchParams.get('lang');
    const target = formulaPanels.find(panel => `#${panel.id}` === url.hash);
    selection.value = Object.hasOwn(choices, linked) ? linked : target?.dataset.formulaSyntax ?? 'formula';
    for (const panel of formulaPanels) {
      if (panel.dataset.formulaSyntax === selection.value) panel.removeAttribute('hidden');
      else panel.setAttribute('hidden', 'until-found');
    }
    return;
  }
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
  if (formulaPanels.some(panel => `#${panel.id}` === url.hash)) {
    url.hash = formulaPanels.find(panel => panel.dataset.formulaSyntax === language).id;
  }
  window.history.replaceState(window.history.state, '', url);
  restoreLanguage();
}

function revealSyntax(event) {
  chooseLanguage(event.currentTarget.dataset.formulaSyntax);
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
  if (props.formulaReference) {
    // Without searchable hidden content, all three sections and their links are available.
    if (!('onbeforematch' in HTMLElement.prototype)) return;
    formulaPanels = [...guide.querySelectorAll('[data-formula-syntax]')];
    for (const panel of formulaPanels) panel.addEventListener('beforematch', revealSyntax);
  }
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
  for (const panel of formulaPanels) panel.removeEventListener('beforematch', revealSyntax);
  window.removeEventListener('popstate', restoreLanguage);
  window.removeEventListener('hashchange', restoreLanguage);
});
</script>

<template>
  <div ref="picker" class="library-picker" :hidden="!selection">
    <label :for="pickerId">{{ formulaReference ? 'Formula syntax' : 'Example language' }}</label>
    <select
      :id="pickerId"
      :name="pickerId"
      :value="selection"
      @change="chooseLanguage($event.target.value)"
    >
      <option v-for="(label, language) in choices" :key="language" :value="language">{{ label }}</option>
    </select>
  </div>
</template>

<style>
.library-picker {
  margin-block-start: 1.5rem;
}

.library-picker label {
  display: block;
  font-weight: 650;
  margin-block-end: .375rem;
}

.library-picker select {
  appearance: auto;
  background: var(--vp-c-bg);
  border: 1px solid var(--vp-c-text-2);
  border-radius: .375rem;
  cursor: pointer;
  font: inherit;
  min-block-size: 3rem;
  min-inline-size: 9rem;
  padding-inline: .75rem;
}

.library-picker select:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

[data-formula-syntax] {
  scroll-margin-block-start: calc(var(--vp-nav-height) + 1.5rem);
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
