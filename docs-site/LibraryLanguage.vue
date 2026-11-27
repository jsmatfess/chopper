<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vitepress';

const props = defineProps({ formulaReference: Boolean });
const router = useRouter();
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
let formulaCodes = [];
let searchablePanels;
let stopNavigationSync;

function fragmentId(hash) {
  try {
    return decodeURIComponent(hash.slice(1));
  } catch {
    return '';
  }
}

function linkedPanel(url) {
  const id = fragmentId(url.hash);
  return formulaPanels.find(panel => panel.heading.id === id);
}

function restoreLanguage(keepSelection = false) {
  const url = new URL(window.location.href);
  if (props.formulaReference) {
    const linked = url.searchParams.get('lang');
    const target = linkedPanel(url);
    const fallback = (keepSelection === true && selection.value) || 'formula';
    selection.value = target?.syntax ?? (Object.hasOwn(choices, linked) ? linked : fallback);
    if ((target && linked && linked !== selection.value) ||
        (keepSelection === true && !linked && selection.value !== 'formula')) {
      url.searchParams.set('lang', selection.value);
      window.history.replaceState(window.history.state, '', url);
    }
    if (searchablePanels) {
      for (const panel of formulaPanels) {
        if (panel.syntax === selection.value) panel.element.removeAttribute('hidden');
        else panel.element.setAttribute('hidden', 'until-found');
      }
    }
    for (const { element, ...syntax } of formulaCodes) {
      const code = syntax[selection.value];
      if (element.textContent !== code) element.textContent = code;
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
  if (linkedPanel(url)) {
    url.hash = formulaPanels.find(panel => panel.syntax === language).heading.id;
  }
  window.history.replaceState(window.history.state, '', url);
  restoreLanguage();
}

function revealSyntax(event) {
  chooseLanguage(event.currentTarget.dataset.formulaSyntax);
}

function alignLinkedSection() {
  const target = document.getElementById(fragmentId(window.location.hash));
  if (target && guide.contains(target)) target.scrollIntoView({ block: 'start' });
}

onMounted(() => {
  guide = picker.value.closest('.vp-doc');
  if (props.formulaReference) {
    searchablePanels = 'onbeforematch' in HTMLElement.prototype;
    formulaCodes = Array.from(guide.querySelectorAll('code[data-formula-rust][data-formula-python]'), element => ({
      element, formula: element.textContent, rust: element.dataset.formulaRust, python: element.dataset.formulaPython,
    }));
    // Without searchable hidden content, leave all notes visible and switch the tables.
    if (!searchablePanels && !formulaCodes.length) return;
    formulaPanels = Array.from(guide.querySelectorAll('[data-formula-syntax]'), element => ({
      element, syntax: element.dataset.formulaSyntax, heading: element.querySelector('h3'),
    }));
    if (searchablePanels) {
      for (const panel of formulaPanels) panel.element.addEventListener('beforematch', revealSyntax);
    }
    // Search can change the fragment through the router without firing hashchange.
    const referencePath = window.location.pathname;
    const previous = router.onBeforePageLoad;
    const sync = async href => {
      const result = await previous?.(href);
      if (result !== false && router.onBeforePageLoad === sync &&
          new URL(href, window.location.href).pathname === referencePath) restoreLanguage(true);
      return result;
    };
    router.onBeforePageLoad = sync;
    stopNavigationSync = () => {
      if (router.onBeforePageLoad === sync) router.onBeforePageLoad = previous;
    };
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
  for (const panel of formulaPanels) panel.element.removeEventListener('beforematch', revealSyntax);
  stopNavigationSync?.();
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

[data-formula-syntax] h3[id] {
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
