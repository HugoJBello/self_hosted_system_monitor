  function enhanceVideoPreview(video, sourceUrl, contentType, hooks) {
    const metadataUrl = new URL(sourceUrl, window.location.href);
    metadataUrl.pathname = metadataUrl.pathname.replace(/\/files\/preview\/$/, "/files/video/metadata/");
    metadataUrl.searchParams.delete("download");
    let stopped = false;
    let directFailed = false;
    let compatibilityAttempted = false;
    let knownState = null;

    const current = () => !stopped && hooks.isCurrent();
    const addSubtitles = (tracks) => {
      if (!current()) return;
      const existing = new Set(Array.from(video.querySelectorAll("track")).map((track) => track.dataset.streamIndex));
      (tracks || []).forEach((track, position) => {
        const key = String(track.index);
        if (existing.has(key)) return;
        const element = document.createElement("track");
        element.kind = "subtitles";
        element.src = track.url;
        element.srclang = track.language || "und";
        element.label = track.label || `Subtitles ${position + 1}`;
        element.dataset.streamIndex = key;
        video.appendChild(element);
      });
    };
    const useCompatible = (state) => {
      if (!current() || compatibilityAttempted || !state.compatible_url) return false;
      compatibilityAttempted = true;
      video.preload = "auto";
      video.src = state.compatible_url;
      video.load();
      video.addEventListener("loadedmetadata", () => {
        if (!current()) return;
        if (video.duration > 0 && video.currentTime === 0) {
          try { video.currentTime = Math.min(0.05, video.duration / 1000); } catch (error) { /* The play button remains available. */ }
        }
      }, {once: true});
      hooks.setCompatibleReady(() => {
        video.play().catch(() => hooks.setStatus("Your browser blocked automatic playback. Press the player play button to continue.", false));
      });
      hooks.setStatus("Compatible preview ready. Press play to start; the original file remains unchanged.", false);
      return true;
    };
    const applyState = (state) => {
      knownState = state;
      addSubtitles(state.subtitles_ready);
      if (state.status === "preparing" && (!state.directly_compatible || directFailed)) {
        hooks.setPreparation(state);
      } else if (!compatibilityAttempted) {
        hooks.setPreparation(null);
      }
      if (state.status === "ready" && (!state.directly_compatible || directFailed)) {
        useCompatible(state);
      } else if (state.status === "preparing" && (!state.directly_compatible || directFailed)) {
        hooks.setStatus("The compatible preview is being prepared below. Playback will start automatically when ready.", false);
      } else if (state.status === "failed" && directFailed) {
        hooks.setPreparation(null);
        hooks.unavailable(state.error || `This browser cannot decode ${contentType || "this video"}.`);
      }
    };
    const poll = async () => {
      if (!current()) return;
      try {
        const response = await fetch(metadataUrl, {headers: {Accept: "application/json"}, cache: "no-store"});
        if (!response.ok) throw new Error("Video analysis failed");
        const state = await response.json();
        if (!current()) return;
        applyState(state);
        if (state.status === "preparing" || state.subtitle_status === "preparing") window.setTimeout(poll, 3000);
      } catch (error) {
        if (directFailed && current()) hooks.unavailable("A compatible preview could not be prepared. You can still download the original video.");
      }
    };

    video.addEventListener("error", () => {
      if (!current()) return;
      if (compatibilityAttempted) {
        hooks.unavailable("The compatible preview could not be played by this browser.");
        return;
      }
      directFailed = true;
      if (!knownState || !useCompatible(knownState)) {
        hooks.setStatus("The original format is not supported. Follow the preparation progress below; playback will begin automatically.", false);
      }
    });
    poll();
    return () => { stopped = true; };
  }
