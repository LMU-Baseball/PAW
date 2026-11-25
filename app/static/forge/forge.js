(function () {
  "use strict";
  const cfg = JSON.parse(document.getElementById("forge-config").textContent);
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  const state = { channels: [], channel: null, posts: new Map(), lastId: 0, season: cfg.season,
                  filter: "", uploads: 0, videoEls: new Map(), since: null, editing: null };
  const POLL_MS = 15000;
  const PARALLEL_PARTS = 3;
  const PART_RETRIES = 4;
  const TS_RE = /\b(\d{1,2}):([0-5]\d)\b/g;

  function api(path, opts = {}) {
    const headers = { "X-CSRFToken": cfg.csrf };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    return fetch(path, { method: opts.method || "GET", headers, credentials: "same-origin",
                         body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined })
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.error || `Something went wrong (${r.status}).`);
        return data;
      });
  }

  // ---------- channel list ----------
  function renderChannels() {
    const list = $("forge-list");
    list.textContent = "";
    const q = state.filter.toLowerCase();
    const shown = state.channels.filter((c) => !q || c.name.toLowerCase().includes(q));
    for (const c of shown) {
      const b = el("button", "forge-chan");
      b.type = "button";
      if (state.channel && state.channel.id === c.id) b.classList.add("active");
      if (c.unread) b.classList.add("unread");
      if (c.sandbox) {
        b.classList.add("sandbox");
        b.title = "Only coaches can see this channel. Use it to try uploads.";
      }
      const nm = el("span", "nm", c.name);
      if (c.mine) nm.appendChild(el("span", "you", "(you)"));
      if (c.sandbox) nm.appendChild(el("span", "you", "· coaches only"));
      b.appendChild(nm);
      if (c.unread) b.appendChild(el("span", "forge-badge", String(c.unread)));
      b.addEventListener("click", () => openChannel(c.id));
      list.appendChild(b);
    }
    if (!shown.length) list.appendChild(el("p", "forge-empty", "No pitchers match."));
  }

  function loadChannels() {
    return api("/forge/api/channels").then((d) => {
      state.channels = d.channels;
      if (state.channel) {
        const c = state.channels.find((x) => x.id === state.channel.id);
        if (c) c.unread = 0;
      }
      renderChannels();
    }).catch(() => {});
  }

  // ---------- feed ----------
  function initials(name) {
    return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((s) => s[0].toUpperCase()).join("");
  }

  // Day dividers carry the date, so a post shows only its time unless it's a
  // reply written on a different day than the post it answers.
  function fmtTime(iso, refIso) {
    const d = new Date(iso);
    const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    if (!refIso || d.toDateString() === new Date(refIso).toDateString()) return time;
    return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " · " + time;
  }

  function dayLabel(iso) {
    const d = new Date(iso);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return "Today";
    if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
    const opts = { weekday: "long", month: "long", day: "numeric" };
    if (d.getFullYear() !== today.getFullYear()) opts.year = "numeric";
    return d.toLocaleDateString([], opts);
  }

  function fmtClock(sec) {
    const s = Math.max(0, Math.floor(sec));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  // Message text with "m:ss" turned into seek links when the post has a video.
  function textNode(body, video) {
    const p = el("div", "fp-text");
    if (!video) { p.textContent = body; return p; }
    let last = 0;
    body.replace(TS_RE, (m, mm, ss, idx) => {
      p.appendChild(document.createTextNode(body.slice(last, idx)));
      const a = el("span", "ts", m);
      a.setAttribute("role", "button");
      a.tabIndex = 0;
      const seek = () => {
        const v = video();
        if (v) { v.currentTime = Number(mm) * 60 + Number(ss); v.play().catch(() => {}); v.scrollIntoView({ block: "center", behavior: "smooth" }); }
      };
      a.addEventListener("click", seek);
      a.addEventListener("keydown", (e) => { if (e.key === "Enter") seek(); });
      p.appendChild(a);
      last = idx + m.length;
    });
    p.appendChild(document.createTextNode(body.slice(last)));
    return p;
  }

  function postNode(post, videoGetter, refIso) {
    const row = el("div", "fp");
    row.dataset.id = post.id;
    row.appendChild(el("div", "fp-av " + (post.author_is_coach ? "coach" : "player"), initials(post.author)));
    const body = el("div", "fp-body");
    const meta = el("div", "fp-meta");
    meta.appendChild(el("strong", null, post.author));
    if (post.author_is_coach) meta.appendChild(el("span", "tag", "COACH"));
    meta.appendChild(document.createTextNode(fmtTime(post.created_at, refIso)));
    if (post.edited) meta.appendChild(el("span", "fp-edited", "(edited)"));
    const editing = state.editing && state.editing.id === post.id;
    if (post.can_edit && !editing) {
      const ed = el("button", "fp-del", "Edit");
      ed.type = "button";
      ed.addEventListener("click", () => {
        state.editing = { id: post.id, text: post.body, focus: true };
        renderFeed();
      });
      meta.appendChild(ed);
    }
    if (post.can_delete) {
      const del = el("button", "fp-del", "Delete");
      del.type = "button";
      del.addEventListener("click", () => deletePost(post.id));
      meta.appendChild(del);
    }
    body.appendChild(meta);
    if (post.deleted) {
      body.appendChild(el("div", "fp-text deleted", "Message deleted"));
    } else if (editing) {
      body.appendChild(editBox(post));
    } else if (post.body) {
      body.appendChild(textNode(post.body, videoGetter));
    }
    row.appendChild(body);
    return { row, body };
  }

  function editBox(post) {
    const box = el("div", "fc-box fp-edit");
    const ta = el("textarea");
    ta.maxLength = 4000;
    ta.value = state.editing.text;
    ta.addEventListener("input", () => { if (state.editing) state.editing.text = ta.value; });
    const save = el("button", "btn", "Save");
    save.type = "button";
    const cancel = el("button", "btn ghost", "Cancel");
    cancel.type = "button";
    const stop = () => { state.editing = null; renderFeed(); };
    const go = () => {
      save.disabled = true;
      api(`/forge/api/posts/${post.id}`, { method: "PATCH", body: { body: ta.value } })
        .then((d) => { state.editing = null; addPosts([d.post]); renderFeed(); })
        .catch((e) => { alertNote(e.message); save.disabled = false; });
    };
    save.addEventListener("click", go);
    cancel.addEventListener("click", stop);
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); }
      if (e.key === "Escape") { e.preventDefault(); stop(); }
    });
    box.appendChild(ta);
    box.appendChild(save);
    box.appendChild(cancel);
    return box;
  }

  function videoBlock(post) {
    const v = post.video;
    const wrap = el("div", "fv");
    if (v.status === "ready") {
      // Reused across re-renders so a poll never restarts a video mid-watch.
      let video = state.videoEls.get(v.id);
      if (!video) {
        video = el("video");
        video.controls = true;
        video.preload = "none";
        video.playsInline = true;
        video.poster = `/forge/video/${v.id}/thumb`;
        video.src = `/forge/video/${v.id}/play`;
        state.videoEls.set(v.id, video);
      }
      wrap.appendChild(video);
      const tools = el("div", "fv-tools");
      if (v.duration_sec) tools.appendChild(el("span", null, fmtClock(v.duration_sec)));
      if (v.muted) tools.appendChild(el("span", null, "No audio"));
      wrap.appendChild(tools);
      return { wrap, video, tools };
    }
    const msg = v.status === "failed"
      ? "This video couldn't be processed" + (v.error && v.error !== "cancelled" ? ` (${v.error})` : "") + "."
      : v.status === "uploading" ? "Uploading…" : "Processing video… it'll appear here in a few minutes.";
    wrap.appendChild(el("div", "fv-status" + (v.status === "failed" ? " failed" : ""), msg));
    return { wrap, video: null, tools: null };
  }

  function renderFeed() {
    const feed = $("forge-feed");
    const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
    const scrollTop = feed.scrollTop;
    const drafts = new Map();
    let focusedParent = null;
    const editTa = feed.querySelector(".fp-edit textarea");
    if (state.editing && editTa && document.activeElement === editTa) state.editing.focus = true;
    feed.querySelectorAll(".fc-box").forEach((box) => {
      const ta = box.querySelector("textarea");
      drafts.set(Number(box.dataset.parent), ta.value);
      if (document.activeElement === ta) focusedParent = Number(box.dataset.parent);
    });
    feed.textContent = "";
    const all = [...state.posts.values()].sort((a, b) => a.id - b.id);
    const tops = all.filter((p) => !p.parent_id);
    const kids = new Map();
    for (const p of all) if (p.parent_id) {
      if (!kids.has(p.parent_id)) kids.set(p.parent_id, []);
      kids.get(p.parent_id).push(p);
    }
    const ch = state.channel || {};
    if (ch.name && ch.joined === false) {
      feed.appendChild(el("p", "forge-empty",
        `${ch.name}'s account is turned off, so they can't post here right now.`));
    } else if (!tops.length) {
      feed.appendChild(el("p", "forge-empty", ch.mine
        ? "This is your channel. Upload a bullpen or send the coaches a message."
        : "Nothing here yet for this season."));
    }
    let lastDay = null;
    for (const post of tops) {
      const day = new Date(post.created_at).toDateString();
      if (day !== lastDay) {
        lastDay = day;
        const sep = el("div", "forge-day");
        sep.appendChild(el("span", null, dayLabel(post.created_at)));
        feed.appendChild(sep);
      }
      let videoEl = null;
      const getVideo = () => videoEl;
      const { row, body } = postNode(post, post.video ? getVideo : null);
      if (post.video) {
        const vb = videoBlock(post);
        videoEl = vb.video;
        body.appendChild(vb.wrap);
        if (vb.tools) {
          const stamp = el("button", null, "+ Comment at current time");
          stamp.type = "button";
          stamp.addEventListener("click", () => openReply(body, post.id, fmtClock(videoEl.currentTime) + " "));
          vb.tools.appendChild(stamp);
        }
      }
      const thread = el("div", "fc");
      for (const c of kids.get(post.id) || []) thread.appendChild(postNode(c, post.video ? getVideo : null, post.created_at).row);
      if (!post.deleted) {
        const reply = el("button", "fc-reply", "Reply");
        reply.type = "button";
        reply.addEventListener("click", () => openReply(body, post.id, ""));
        thread.appendChild(reply);
      }
      body.appendChild(thread);
      feed.appendChild(row);
    }
    for (const [parentId, text] of drafts) {
      const row = feed.querySelector(`.fp[data-id="${parentId}"] > .fp-body`);
      if (row) openReply(row, parentId, "", text, parentId === focusedParent);
    }
    const ed = feed.querySelector(".fp-edit textarea");
    if (ed && state.editing && state.editing.focus) {
      state.editing.focus = false;
      ed.focus({ preventScroll: true });
      ed.setSelectionRange(ed.value.length, ed.value.length);
    }
    if (atBottom || state.scrollToEnd) { feed.scrollTop = feed.scrollHeight; state.scrollToEnd = false; }
    else feed.scrollTop = scrollTop;
  }

  function openReply(body, parentId, prefill, draft, focus = true) {
    let box = body.querySelector(":scope > .fc > .fc-box");
    if (!box) {
      box = el("div", "fc-box");
      box.dataset.parent = parentId;
      const ta = el("textarea");
      ta.placeholder = "Reply… (type 2:31 to link a moment in the video)";
      ta.maxLength = 4000;
      const send = el("button", "btn", "Reply");
      send.type = "button";
      const go = () => {
        const text = ta.value.trim();
        if (!text) return;
        send.disabled = true;
        api(`/forge/api/channels/${state.channel.id}/posts`, { method: "POST", body: { body: text, parent_id: parentId } })
          .then((d) => { box.remove(); addPosts([d.post]); renderFeed(); })
          .catch((e) => { alertNote(e.message); send.disabled = false; });
      };
      send.addEventListener("click", go);
      ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } });
      box.appendChild(ta);
      box.appendChild(send);
      body.querySelector(":scope > .fc").appendChild(box);
    }
    const ta = box.querySelector("textarea");
    if (draft) ta.value = draft;
    if (prefill) ta.value = prefill + ta.value;
    if (focus) {
      ta.focus({ preventScroll: !prefill });
      ta.setSelectionRange(ta.value.length, ta.value.length);
    }
  }

  function addPosts(posts) {
    for (const p of posts) {
      state.posts.set(p.id, p);
      if (p.id > state.lastId) state.lastId = p.id;
    }
  }

  function alertNote(msg) {
    const n = $("forge-note");
    n.textContent = msg;
    n.style.color = "var(--crimson)";
    clearTimeout(alertNote.t);
    alertNote.t = setTimeout(() => { n.textContent = ""; n.style.color = ""; }, 6000);
  }

  function openChannel(id) {
    state.channel = { id };
    state.posts = new Map();
    state.videoEls = new Map();
    state.lastId = 0;
    state.since = null;
    state.editing = null;
    state.season = cfg.season;
    $("forge").classList.add("open");
    $("forge-compose").hidden = false;
    $("forge-feed").textContent = "";
    $("forge-feed").appendChild(el("p", "forge-empty", "Loading…"));
    const c = state.channels.find((x) => x.id === id);
    if (c) { c.unread = 0; $("forge-title").textContent = c.name; }
    renderChannels();
    try { history.replaceState(null, "", `#${id}`); } catch (e) { /* ignore */ }
    loadPosts(true);
  }

  function loadPosts(full) {
    if (!state.channel) return Promise.resolve();
    const id = state.channel.id;
    const pending = [...state.posts.values()]
      .filter((p) => p.video && (p.video.status === "queued" || p.video.status === "processing"))
      .map((p) => p.video.id);
    const qs = full ? `season=${encodeURIComponent(state.season)}`
                    : `after=${state.lastId}` + (state.since ? `&since=${encodeURIComponent(state.since)}` : "") +
                      (pending.length ? `&videos=${pending.join(",")}` : "");
    return api(`/forge/api/channels/${id}/posts?${qs}`).then((d) => {
      if (!state.channel || state.channel.id !== id) return;
      state.channel = d.channel;
      state.since = d.now;
      $("forge-title").textContent = d.channel.name;
      const sel = $("forge-season");
      if (full) {
        sel.textContent = "";
        for (const s of d.channel.seasons) {
          const o = el("option", null, s);
          o.value = s;
          if (s === state.season) o.selected = true;
          sel.appendChild(o);
        }
        sel.hidden = d.channel.seasons.length < 2;
        state.scrollToEnd = true;
      }
      const ub = $("forge-upload-btn");
      ub.hidden = !(d.channel.can_upload && cfg.uploads_enabled);
      $("forge-note").textContent = d.channel.can_upload && !cfg.uploads_enabled
        ? "Video uploads are being set up -- messages work now." : "";
      let changed = false;
      for (const p of state.posts.values()) {
        const v = p.video && d.videos && d.videos[p.video.id];
        if (v && v.status !== p.video.status) { p.video = v; changed = true; }
      }
      if (d.posts.length || full || changed) {
        addPosts(d.posts);
        renderFeed();
      }
      if (d.posts.length || full) api(`/forge/api/channels/${id}/read`, { method: "POST", body: {} }).catch(() => {});
    }).catch((e) => { if (full) { $("forge-feed").textContent = ""; $("forge-feed").appendChild(el("p", "forge-empty", e.message)); } });
  }

  function sendMessage() {
    const ta = $("forge-text");
    const text = ta.value.trim();
    if (!text || !state.channel) return;
    $("forge-send").disabled = true;
    api(`/forge/api/channels/${state.channel.id}/posts`, { method: "POST", body: { body: text } })
      .then((d) => { ta.value = ""; addPosts([d.post]); state.scrollToEnd = true; renderFeed(); })
      .catch((e) => alertNote(e.message))
      .finally(() => { $("forge-send").disabled = false; ta.focus(); });
  }

  function deletePost(id) {
    if (!window.confirm("Delete this message?")) return;
    api(`/forge/api/posts/${id}`, { method: "DELETE" })
      .then(() => { const p = state.posts.get(id); if (p) { p.deleted = true; p.body = ""; p.video = null; p.can_delete = false; } renderFeed(); })
      .catch((e) => alertNote(e.message));
  }

  // ---------- video upload ----------
  function readDuration(file) {
    return new Promise((resolve) => {
      const v = document.createElement("video");
      v.preload = "metadata";
      const url = URL.createObjectURL(file);
      const done = (d) => { URL.revokeObjectURL(url); resolve(d); };
      v.onloadedmetadata = () => done(isFinite(v.duration) ? v.duration : 0);
      v.onerror = () => done(0);
      setTimeout(() => done(0), 8000);
      v.src = url;
    });
  }

  function putPart(url, blob, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", url);
      xhr.upload.onprogress = (e) => onProgress(e.loaded);
      xhr.onload = () => {
        const etag = xhr.getResponseHeader("ETag");
        if (xhr.status >= 200 && xhr.status < 300 && etag) resolve(etag);
        else reject(new Error(`part failed (${xhr.status})`));
      };
      xhr.onerror = () => reject(new Error("network error"));
      xhr.send(blob);
    });
  }

  function startUploadPanel(file, duration) {
    const channelId = state.channel.id;
    const panel = el("div", "fu");
    panel.appendChild(el("div", "fu-name", `${file.name} · ${(file.size / 1048576).toFixed(0)} MB` +
      (duration ? ` · ${fmtClock(duration)}` : "")));
    const note = el("textarea");
    note.placeholder = "Add a note for the coaches (what you worked on, what felt off)…";
    note.maxLength = 4000;
    panel.appendChild(note);
    const muteRow = el("label", "fu-mute");
    const mute = document.createElement("input");
    mute.type = "checkbox";
    muteRow.appendChild(mute);
    muteRow.appendChild(document.createTextNode(" Remove audio"));
    panel.appendChild(muteRow);
    const bar = el("div", "fu-bar");
    const fill = el("div");
    bar.appendChild(fill);
    bar.hidden = true;
    panel.appendChild(bar);
    const msg = el("div", "fu-msg");
    panel.appendChild(msg);
    const actions = el("div", "fu-actions");
    const go = el("button", "btn", "Upload");
    const cancel = el("button", "btn ghost", "Cancel");
    go.type = cancel.type = "button";
    actions.appendChild(go);
    actions.appendChild(cancel);
    panel.appendChild(actions);
    $("forge-uploads").appendChild(panel);
    note.focus();

    let cancelled = false;
    let videoId = null;
    cancel.addEventListener("click", () => {
      cancelled = true;
      if (videoId) api(`/forge/api/uploads/${videoId}/abort`, { method: "POST", body: {} }).catch(() => {});
      panel.remove();
    });

    go.addEventListener("click", async () => {
      go.disabled = true;
      note.disabled = true;
      mute.disabled = true;
      bar.hidden = false;
      msg.className = "fu-msg";
      msg.textContent = "Starting upload… keep this page open.";
      state.uploads += 1;
      try {
        const start = await api(`/forge/api/channels/${channelId}/uploads`, { method: "POST",
          body: { name: file.name, size: file.size, type: file.type, duration,
                  strip_audio: mute.checked } });
        videoId = start.video_id;
        const n = start.urls.length;
        const loaded = new Array(n).fill(0);
        const etags = new Array(n);
        let next = 0;
        const update = () => {
          const pct = Math.min(100, (loaded.reduce((a, b) => a + b, 0) / file.size) * 100);
          fill.style.width = pct.toFixed(1) + "%";
          msg.textContent = `Uploading… ${pct.toFixed(0)}% — keep this page open.`;
        };
        const worker = async () => {
          while (!cancelled && next < n) {
            const i = next++;
            const blob = file.slice(i * start.part_size, Math.min(file.size, (i + 1) * start.part_size));
            for (let attempt = 1; ; attempt++) {
              try {
                etags[i] = await putPart(start.urls[i], blob, (b) => { loaded[i] = b; update(); });
                loaded[i] = blob.size;
                update();
                break;
              } catch (e) {
                loaded[i] = 0;
                if (attempt >= PART_RETRIES || cancelled) throw e;
                msg.textContent = "Connection hiccup — retrying…";
                await new Promise((r) => setTimeout(r, 1500 * attempt));
              }
            }
          }
        };
        await Promise.all(Array.from({ length: Math.min(PARALLEL_PARTS, n) }, worker));
        if (cancelled) return;
        msg.textContent = "Finishing…";
        const done = await api(`/forge/api/uploads/${videoId}/complete`, { method: "POST",
          body: { parts: etags.map((etag, i) => ({ n: i + 1, etag })), note: note.value } });
        if (state.channel && state.channel.id === channelId) {
          addPosts([done.post]);
          state.scrollToEnd = true;
          renderFeed();
        }
        panel.remove();
      } catch (e) {
        if (cancelled) return;
        msg.className = "fu-msg err";
        msg.textContent = `Upload failed: ${e.message} Check your connection and try again.`;
        if (videoId) api(`/forge/api/uploads/${videoId}/abort`, { method: "POST", body: {} }).catch(() => {});
        videoId = null;
        go.disabled = false;
        go.textContent = "Try again";
        note.disabled = false;
        mute.disabled = false;
      } finally {
        state.uploads -= 1;
      }
    });
  }

  async function onFileChosen() {
    const input = $("forge-file");
    const file = input.files && input.files[0];
    input.value = "";
    if (!file || !state.channel) return;
    if (file.size > cfg.max_bytes) return alertNote("That video is over 4 GB. Trim it in Photos and try again.");
    const duration = await readDuration(file);
    if (duration > cfg.max_duration + 30) return alertNote("Videos can be up to 20 minutes. Trim it in Photos and try again.");
    startUploadPanel(file, duration);
  }

  // ---------- "do you pitch?" for accounts made before sign-up asked ----------
  function renderAsk() {
    const box = $("forge-claim");
    if (!cfg.ask_player_type) return;
    box.hidden = false;
    box.appendChild(el("strong", null, "Do you pitch?"));
    box.appendChild(el("p", null, "Pitchers get their own channel here for bullpen video."));
    const type = el("select");
    for (const [v, t] of [["", "Choose…"], ["position", "Position player"], ["pitcher", "Pitcher"], ["both", "Both"]]) {
      const o = el("option", null, t); o.value = v; type.appendChild(o);
    }
    const save = el("button", "btn", "Save");
    save.type = "button";
    const err = el("div", "err");
    save.addEventListener("click", () => {
      if (!type.value) { err.textContent = "Pick position player, pitcher, or both."; return; }
      save.disabled = true;
      api("/forge/api/player-type", { method: "POST", body: { player_type: type.value } })
        .then((d) => { location.hash = d.channel_id ? String(d.channel_id) : ""; location.reload(); })
        .catch((e) => { err.textContent = e.message; save.disabled = false; });
    });
    box.appendChild(type);
    box.appendChild(save);
    box.appendChild(err);
  }

  // ---------- wiring ----------
  renderAsk();
  $("forge-search").addEventListener("input", (e) => { state.filter = e.target.value; renderChannels(); });
  $("forge-send").addEventListener("click", sendMessage);
  $("forge-text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  $("forge-upload-btn").addEventListener("click", () => $("forge-file").click());
  $("forge-file").addEventListener("change", onFileChosen);
  $("forge-back").addEventListener("click", () => { $("forge").classList.remove("open"); state.channel = null; renderChannels(); loadChannels(); });
  $("forge-season").addEventListener("change", (e) => { state.season = e.target.value; state.posts = new Map(); state.lastId = 0; loadPosts(true); });
  window.addEventListener("beforeunload", (e) => { if (state.uploads > 0) { e.preventDefault(); e.returnValue = ""; } });

  setInterval(() => { if (!document.hidden) loadPosts(false); }, POLL_MS);
  setInterval(() => { if (!document.hidden) loadChannels(); }, POLL_MS * 2);

  loadChannels().then(() => {
    const fromHash = Number((location.hash || "").slice(1));
    const target = state.channels.find((c) => c.id === fromHash) ||
                   (window.innerWidth > 720 && state.channels.find((c) => c.mine));
    if (target) openChannel(target.id);
  });
})();
