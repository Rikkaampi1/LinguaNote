# LinguaNote

#### Video Demo: https://youtu.be/qbMHjkum53g
#### Description:

LinguaNote is a web application that helps language learners collect vocabulary from texts into a personal glossary and review it using a spaced repetition system. It is designed for learners who translate articles, books, or course materials and want a single place to store new words, see them in context, and systematically review them over time.

After registering and logging in, a user can create projects, each of which usually represents a specific course, book, or topic. Inside a project, the user can add multiple texts that they are currently studying or translating. The main editor page shows the original text on the left and the user’s own translation on the right. While working on the translation, the user can select any word or phrase in the source text to open a popup with dictionary information and a small form for saving that selection as a glossary entry, including their own translation and an optional note.

All saved entries appear in the project’s glossary. Each term stores the original expression, the user’s translation, an optional note, the context sentence in which the term appeared, and the direction of translation. From the glossary, the user can delete terms they no longer need. The Study page then turns these glossary entries into flashcards. The user sees a term, tries to recall its translation, reveals the answer, and rates how well they remembered it, for example by choosing options like “Again” or “Good”. These ratings are used to schedule the next review of each term.

Technically, LinguaNote is built with Python and Flask on the backend. It uses Flask-Login for user authentication, ensuring that each user has their own projects, texts, and terms. Data is stored in a SQLite database through SQLAlchemy models, including `User`, `Project`, `Text`, and `Term`. Each term tracks fields for spaced repetition such as interval, ease factor, repetition count, and next review date. The study routes use these fields together with a simplified SM‑2 algorithm to update the schedule after each review.

On the frontend, the application uses Bootstrap for layout and visual components, along with custom CSS to style cards, navigation, and the two-column editor with independently scrollable columns. Vanilla JavaScript handles text selection in the editor, positions and shows the popup, sends JSON requests to the backend to save terms and translations, and drives the Study interface in the browser. For dictionary data, the application calls the Free Dictionary API and optionally the Lingua Robot API via the `requests` library, combining definitions, examples, and synonyms into a compact format that is displayed in the popup.

Overall, LinguaNote aims to combine three things into a single workflow: translating texts, building a structured personal glossary with real context, and reviewing vocabulary using spaced repetition. This project allowed me to practice full‑stack web development with Flask, work with a relational database through an ORM, integrate external APIs, and implement a simple spaced repetition algorithm on top of a real learning workflow.
