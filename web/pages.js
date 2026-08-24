/* Shared behaviour for the prose pages: same theme and language choices as the
   tool, read from the same localStorage keys. No i18n dictionary here -- the
   prose exists twice in the markup and the root's lang attribute selects it. */

import { PROJECT, projectLinks } from './project.js';

const root = document.documentElement;

function applyLang(lang) {
  root.lang = lang;
  root.dir = lang === 'ar' ? 'rtl' : 'ltr';
  localStorage.setItem('lang', lang);
  const btn = document.querySelector('#lang-toggle');
  if (btn) btn.textContent = lang === 'ar' ? 'English' : 'العربية';
  renderAuthor();
  renderProjectLinks(lang);
}

function renderAuthor() {
  for (const node of document.querySelectorAll('.author-name')) {
    node.textContent = PROJECT.author;
  }
}

function renderProjectLinks(lang) {
  const host = document.querySelector('#project-links');
  if (!host) return;
  host.textContent = '';
  for (const l of projectLinks(lang)) {
    const a = document.createElement('a');
    a.href = l.href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    if (l.ltr) {
      const span = document.createElement('span');
      span.className = 'ltr';
      span.textContent = l.label;
      a.append(span);
    } else {
      a.textContent = l.label;
    }
    host.append(a);
  }
}

function applyTheme(mode) {
  if (mode === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', mode);
  localStorage.setItem('theme', mode);
  const dark = mode === 'dark' ||
    (mode === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  const btn = document.querySelector('#theme-toggle');
  if (btn) {
    btn.textContent = root.lang === 'ar' ? (dark ? 'داكن' : 'فاتح')
                                         : (dark ? 'Dark' : 'Light');
  }
}

applyLang(localStorage.getItem('lang') || 'ar');
applyTheme(localStorage.getItem('theme') || 'system');

document.querySelector('#lang-toggle')?.addEventListener('click', () => {
  applyLang(root.lang === 'ar' ? 'en' : 'ar');
  applyTheme(localStorage.getItem('theme') || 'system');
});
document.querySelector('#theme-toggle')?.addEventListener('click', () => {
  const now = root.getAttribute('data-theme');
  const dark = now ? now === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(dark ? 'light' : 'dark');
});
