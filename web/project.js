/* Who made this and where to reach them. Kept in one file so the footer, the
   prose pages, and the README stay in step.
 *
 * `author` is the person, as named in LICENSE. `HANDLE` is the account, and
 * every URL is built from it so the two cannot drift apart -- change the handle
 * in one place and the repository, profile and X links all follow.
 *
 * Set `x` to '' if you would rather not link an X account; the link then simply
 * does not render, instead of shipping a link to whoever owns that handle.
 */
const HANDLE = 'Mulhamx4';

export const PROJECT = {
  author: 'Mulham',
  handle: HANDLE,
  repo: `https://github.com/${HANDLE}/arabic-font-merge`,
  github: `https://github.com/${HANDLE}`,
  x: HANDLE,                  // X handle, no @
  license: 'MIT',
};

/* The skill, as it exists in this repository. The page fetches these and zips
   them in the browser, so the download is always exactly what is committed
   here -- there is no separately built artefact to fall out of date. */
export const SKILL_FILES = [
  'SKILL.md',
  'requirements.txt',
  'LICENSE',
  'NOTICE.md',
  'README.md',
  'README.ar.md',
  'CONTRIBUTING.md',
  'scripts/fontkit.py',
  'scripts/build_family.py',
  'scripts/inspect_fonts.py',
  'scripts/verify_font.py',
  'scripts/make_proof.py',
  'assets/currencies.json',
  'assets/saudi-riyal.svg',
  'assets/uae-dirham.svg',
  'assets/omani-rial.svg',
  'references/opentype-notes.md',
  'references/troubleshooting.md',
  'evals/evals.json',
];

export function projectLinks(lang) {
  const ar = lang === 'ar';
  const links = [
    { href: PROJECT.repo, label: ar ? 'المستودع' : 'Repository' },
    { href: PROJECT.repo + '/issues',
      label: ar ? 'اقتراح أو ملاحظة' : 'Suggestions & issues' },
    { href: PROJECT.github, label: 'GitHub' },
  ];
  if (PROJECT.x) {
    // `ltr` marks a label whose own direction must survive an RTL page --
    // "@handle" otherwise renders as "handle@".
    links.push({ href: `https://x.com/${PROJECT.x}`, label: `@${PROJECT.x}`, ltr: true });
  }
  return links;
}
