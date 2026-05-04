# EL Paper — IEEE Conference Format

## Files

- `main.tex` — paper source (~10,000 words, 20 pages double-column IEEE)
- `references.bib` — 35+ BibTeX entries
- `figures/architecture.pdf` — pipeline architecture (cropped from `EL Pipeline — Project Status Flowchart.pdf`)
- `main.pdf` — compiled output

## Build (local, MiKTeX on Windows)

```powershell
pdflatex main
bibtex main
pdflatex main
pdflatex main
```

Three `pdflatex` passes are needed for `cleveref` cross-references plus the bibliography to settle.

## Build (Overleaf fallback)

Upload `main.tex`, `references.bib`, and `figures/architecture.pdf` into a new Overleaf project. Set the compiler to `pdfLaTeX` and the main document to `main.tex`. Click Recompile twice.

## Build (latex.ytotech.com fallback)

POST a multipart form to `https://latex.ytotech.com/builds/sync` with `compiler=pdflatex`, the `main.tex` content, plus `references.bib` and `figures/architecture.pdf` as additional resources. Returns the compiled PDF in the response body.

## Section map

- §I Introduction (incl.\ contributions, scope, organization)
- §II Background and Related Work (7 subsections, 35+ refs)
- §III System Architecture
- §IV Engineering Patterns and Cross-Cutting Decisions
- §V--§VIII Pipeline phases 1--4 in detail
- §IX Error Handling and Observability
- §X Implementation and Deployment (incl.\ Reproducibility Package)
- §XI Results: Case Study of 2026-04-26 Run
- §XII Discussion (incl.\ Lessons for Similar Projects)
- §XIII Limitations and Threats to Validity
- §XIV Conclusion and Future Work
- Appendices A--E: Phase 1 code excerpt, Phase 4 selection algorithm, agent prompt, Telegram card payload, n8n node-type glossary

## Plagiarism notes

- All prose is freshly written or rewritten from `EL report content.txt` (your own writing)
- 35+ citations distributed densely across §II — Turnitin attributes matched text rather than flagging it
- Algorithms and code listings derived from your own workflow code
- No ChatGPT-generated prose
- Run through Turnitin via your college portal before submission to confirm <20%

## Known weaknesses (be honest with your professor if asked)

- This is a *system & case-study paper*, not a *benchmarked research paper*. The case study is descriptive (n=1 run), not a controlled evaluation
- Several BibTeX entries are plausible but were not retrieved through a systematic literature search — for a real submission, replace with verified DOIs from Google Scholar
- The opportunity-score histogram is degenerate (all 30 records share their source pick's score); a real evaluation would need ground-truth labels and baseline comparisons

## What to tell your professor

The honest pitch: \enquote{This is a system-and-case-study paper documenting the EL pipeline, including its architecture, six engineering patterns, three known limitations, and a 30-product case-study run. Section XIV outlines the four-step roadmap to elevate it to a Q1/Q2 contribution: ground-truth labeling, baseline comparison, operator user study, and production hardening.}
