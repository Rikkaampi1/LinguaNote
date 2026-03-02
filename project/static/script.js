document.addEventListener("DOMContentLoaded", function () {
  console.log("SCRIPT LOADED");

  const original = document.getElementById("original-text");
  const popup = document.getElementById("lookup-popup");
  const popupContent = document.getElementById("lookup-content");
  const btnSaveFull = document.getElementById("btn-save-full-translation");
  const editorRoot = document.getElementById("editor-root");

  let PROJECT_ID = null;
  let TEXT_ID = null;

  if (editorRoot) {
    PROJECT_ID = editorRoot.getAttribute("data-project-id");
    TEXT_ID = editorRoot.getAttribute("data-text-id");
  }

  let lastSelectedText = "";
  let lastLookupData = null;
  let lastKnownTerm = null;

  // ---------------------- EDITOR / LOOKUP LOGIC ----------------------
  function getDirection() {
    const radios = document.querySelectorAll('input[name="source_lang"]');
    let src = "en";
    for (const r of radios) {
      if (r.checked) {
        src = r.value;
        break;
      }
    }
    return src === "en" ? "en-ru" : "ru-en";
  }

  function getCurrentContext() {
    return lastSelectedText;
  }

  async function findKnownTerm(text) {
    if (!PROJECT_ID) return null;

    const norm = text.trim().toLowerCase();
    const params = new URLSearchParams({
      term: norm,
      project_id: PROJECT_ID,
    });

    try {
      const resp = await fetch(`/terms/find?${params.toString()}`);
      if (!resp.ok) return null;
      const data = await resp.json();
      if (data.found) {
        return data;
      }
      return null;
    } catch (err) {
      console.error("Error in findKnownTerm", err);
      return null;
    }
  }

  async function showLookup(event) {
    console.log("showLookup called");

    const selection = window.getSelection();
    let text = selection.toString().trim();
    console.log("selected text:", text);

    if (!text) {
      popup.classList.remove("visible");
      popup.style.display = "none";
      lastSelectedText = "";
      lastLookupData = null;
      lastKnownTerm = null;
      return;
    }

    // нормализация
    text = text.replace(/\s+/g, " ");
    lastSelectedText = text;

    // позиция относительно выделения
    const range = selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
    let rect = null;
    if (range) {
      rect = range.getBoundingClientRect();
    }

    // делаем попап видимым вне экрана, чтобы узнать размеры
    popup.style.visibility = "hidden";
    popup.style.display = "block";
    popup.style.top = "-9999px";
    popup.style.left = "-9999px";

    const popupWidth = popup.offsetWidth;
    const popupHeight = popup.offsetHeight;

    let top = 0;
    let left = 0;

    if (rect) {
      // базовая позиция: над выделением, по центру
      top = rect.top - popupHeight - 8;
      left = rect.left + rect.width / 2 - popupWidth / 2;
    } else {
      // запасной вариант — по курсору
      top = event.clientY + 10;
      left = event.clientX;
    }

    // ограничения по окну (fixed, без scrollX/Y)
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = document.documentElement.clientHeight;

    const maxLeft = viewportWidth - popupWidth - 8;
    const minLeft = 8;
    left = Math.max(minLeft, Math.min(left, maxLeft));

    const minTop = 8;
    // если выше не влезает — показываем под выделением
    if (top < minTop && rect) {
      top = rect.bottom + 8;
    }
    const maxTop = viewportHeight - popupHeight - 8;
    top = Math.max(minTop, Math.min(top, maxTop));

    popup.style.top = `${top}px`;
    popup.style.left = `${left}px`;
    popup.style.visibility = "visible";
    popup.classList.add("visible");
    console.log("popup shown at:", popup.style.left, popup.style.top);

    const direction = getDirection();

    popupContent.innerHTML = `
      <em>Looking up "<strong>${text}</strong>" (${direction})...</em>
    `;

    // 1. глоссарий
    lastKnownTerm = await findKnownTerm(text);

    // 2. словарь + MT
    try {
      const params = new URLSearchParams({
        term: text,
        direction: direction,
        project_id: PROJECT_ID || "",
      });
      console.log("Lookup URL:", `/lookup?${params.toString()}`);

      const resp = await fetch(`/lookup?${params.toString()}`);
      console.log("lookup status:", resp.status);

      if (!resp.ok) {
        popupContent.innerHTML = `
          <strong>${text}</strong><br>
          <small class="text-danger">Lookup failed (${resp.status}).</small>
        `;
        lastLookupData = null;
        return;
      }

      const data = await resp.json();
      console.log("lookup data:", data);

      lastLookupData = data;

      let html = "";

      // Заголовок
      html += `<div class="mb-1">
        <strong>${data.original}</strong>
        <small class="text-muted">(${data.direction})</small>
      </div>`;

      // поле для твоего перевода
      let suggested = "";
      if (lastKnownTerm && lastKnownTerm.translation) {
        suggested = lastKnownTerm.translation;
      } else if (data.translation) {
        suggested = data.translation;
      }

      html += `
        <div class="mt-1">
          <label class="small text-muted mb-1">Your translation</label>
          <input type="text"
                 class="form-control form-control-sm"
                 id="popup-translation-input"
                 value="${(suggested || "").replace(/"/g, "&quot;")}">
        </div>
      `;

      // MT как справка
      if (data.translation) {
        html += `
          <div class="mt-2">
            <span class="badge badge-primary mr-1">MT</span>
            <small><strong>Machine translation:</strong> ${data.translation}</small>
          </div>
        `;
      } else {
        html += `
          <div class="mt-2 text-muted">
            <span class="badge badge-secondary mr-1">MT</span>
            <small>No machine translation</small>
          </div>
        `;
      }

      // словарь
      const dict = data.dictionary;
      if (dict) {
        html += `<div class="mt-2">
          <strong>${dict.term || data.original}</strong>`;
        if (dict.phonetic) {
          html += ` <small>[${dict.phonetic}]</small>`;
        }
        html += `</div>`;

        if (dict.partOfSpeech) {
          html += `<div><small><em>${dict.partOfSpeech}</em></small></div>`;
        }

        if (dict.definitions && dict.definitions.length > 0) {
          html += "<ol class='mb-1 mt-1'>";
          dict.definitions.forEach(function (def) {
            html += "<li>";
            html += def.definition;
            if (def.example) {
              html += `<br><small class="text-muted">Example: ${def.example}</small>`;
            }
            html += "</li>";
          });
          html += "</ol>";
        }

        if (dict.synonyms && dict.synonyms.length > 0) {
          html += `<div><small><strong>Synonyms:</strong> ${dict.synonyms.join(", ")}</small></div>`;
        }

        if (dict.source === "linguarobot") {
          html += `<div class="mt-1">
            <small class="text-info">Source: Lingua Robot</small>
          </div>`;
        } else if (dict.source === "freedictionary") {
          html += `<div class="mt-1">
            <small class="text-muted">Source: Free Dictionary API</small>
          </div>`;
        }
      } else {
        html += `<div class="mt-2 text-muted">
          <small>No dictionary data</small>
        </div>`;
      }

      if (lastKnownTerm && lastKnownTerm.translation) {
        html += `<div class="mt-1">
          <small class="text-info">
            This term is already in your glossary. Saving will update its translation.
          </small>
        </div>`;
      }

      // Кнопки попапа
      html += `
        <div class="mt-3 d-flex justify-content-between">
          <button type="button"
                  id="popup-btn-glossary"
                  class="btn btn-sm btn-success">
            Save to glossary
          </button>
          <button type="button"
                  id="popup-btn-study"
                  class="btn btn-sm btn-outline-info">
            Save & learn
          </button>
        </div>
      `;

      popupContent.innerHTML = html;

      const popupBtnGlossary = document.getElementById("popup-btn-glossary");
      const popupBtnStudy = document.getElementById("popup-btn-study");

      if (popupBtnGlossary) {
        popupBtnGlossary.addEventListener("click", function (e) {
          e.stopPropagation();
          saveTerm(false);
        });
      }
      if (popupBtnStudy) {
        popupBtnStudy.addEventListener("click", function (e) {
          e.stopPropagation();
          saveTerm(true);
        });
      }
    } catch (err) {
      console.error(err);
      popupContent.innerHTML = `
        <strong>${text}</strong><br>
        <small class="text-danger">Error while loading dictionary/translation.</small>
      `;
      lastLookupData = null;
    }
  }

  async function saveTerm(addToStudy) {
    if (!PROJECT_ID) {
      alert("Project is not set. Cannot save term.");
      return;
    }
    if (!lastSelectedText) {
      alert("No text selected.");
      return;
    }

    const direction = getDirection();
    let translation = "";
    const inputEl = document.getElementById("popup-translation-input");
    if (inputEl) {
      translation = inputEl.value.trim();
    }

    const payload = {
      term: lastSelectedText,
      translation: translation,
      context: getCurrentContext(),
      direction: direction,
      project_id: PROJECT_ID,
      text_id: TEXT_ID,
      add_to_study: addToStudy,
    };

    try {
      const resp = await fetch("/terms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        console.error("Failed to save term", resp.status);
        alert("Failed to save term");
        return;
      }

      const data = await resp.json();
      console.log("Saved term:", data);

      if (addToStudy) {
        alert("Added to study list");
      } else {
        alert("Term saved");
      }
    } catch (err) {
      console.error(err);
      alert("Error while saving term");
    }
  }

  // Сохранение полного перевода текста
  if (btnSaveFull) {
    btnSaveFull.addEventListener("click", async function (event) {
      event.stopPropagation();

      const textarea = document.getElementById("translation-text");
      if (!textarea) {
        alert("Translation field not found.");
        return;
      }

      const fullTranslation = textarea.value.trim();
      if (!fullTranslation) {
        if (!confirm("Translation is empty. Save anyway?")) {
          return;
        }
      }

      if (!TEXT_ID) {
        alert("Text ID is not set. Cannot save full translation.");
        return;
      }

      try {
        const resp = await fetch(`/texts/${TEXT_ID}/translation`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ translation: fullTranslation }),
        });

        if (!resp.ok) {
          console.error("Failed to save full translation", resp.status);
          alert("Failed to save full translation");
          return;
        }

        const data = await resp.json();
        console.log("Full translation saved:", data);
        alert("Full translation saved");
      } catch (err) {
        console.error(err);
        alert("Error while saving full translation");
      }
    });
  }

  // События для редактора (только если есть original)
  if (original && popup && popupContent) {
    original.addEventListener("mouseup", function (event) {
      showLookup(event);
    });

    document.addEventListener("click", function (event) {
      const isInsideOriginal = original.contains(event.target);
      const isInsidePopup = popup.contains(event.target);

      if (!isInsideOriginal && !isInsidePopup) {
        popup.classList.remove("visible");
        popup.style.display = "none";
      }
    });
  }

  // ---------------------- STUDY PAGE LOGIC ----------------------
  const btnRemove = document.getElementById("btn-remove");

  if (btnRemove && typeof words !== "undefined" && typeof showCard === "function") {
    btnRemove.addEventListener("click", async () => {
      const word = words[currentIndex];
      if (!word) return;

      if (!confirm("Remove this term from study (keep in glossary)?")) {
        return;
      }

      try {
        const resp = await fetch(`/terms/${word.id}/unstudy`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });
        if (!resp.ok) {
          alert("Failed to remove from study");
          return;
        }
        // убираем карточку из очереди и показываем следующую
        words.splice(currentIndex, 1);
        if (currentIndex >= words.length) {
          currentIndex = 0;
        }
        showCard();
      } catch (e) {
        console.error(e);
        alert("Error while removing from study");
      }
    });
  }
});
