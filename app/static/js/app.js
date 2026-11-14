/* ==========================================================================
   影库（YingKu）前端原生交互脚本
   不依赖任何前端框架；统一处理深浅主题切换、轮播与横向轨道、MPC-HC 播放拉起、
   首次引导检测、AList 网盘目录浏览、名称识别分桶入库及后台管理交互。
   ========================================================================== */
(function () {
  "use strict";

  const prefersReducedMotion = () =>
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function mediaImgUrl(relPath) {
    const clean = String(relPath || "").trim().replace(/^\/+/, "");
    return clean ? `/media-cache/${clean}` : "";
  }

  async function apiJson(url, options = {}) {
    const opts = Object.assign(
      {
        headers: { "Content-Type": "application/json", Accept: "application/json" },
      },
      options
    );
    if (opts.body && typeof opts.body !== "string") {
      opts.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(url, opts);
    let data = {};
    try {
      data = await resp.json();
    } catch (_e) {
      data = { ok: false, message: `服务器响应异常 (HTTP ${resp.status})` };
    }
    return { status: resp.status, ok: resp.ok && data.ok !== false, data };
  }

  /* ---------- 1. 全局轻提示 Toast ---------- */
  function showToast(message, state = "info") {
    const stack = document.getElementById("toast-stack");
    if (!stack || !message) return;

    const item = document.createElement("div");
    item.className = "toast-item";
    const dotColor =
      state === "ok"
        ? "var(--status-ok-fg)"
        : state === "error"
        ? "var(--status-err-fg)"
        : state === "warn"
        ? "var(--status-warn-fg)"
        : "var(--accent)";

    item.innerHTML = `
      <span class="w-2 h-2 rounded-full mt-1.5 shrink-0" style="background-color: ${dotColor};"></span>
      <div class="flex-1 leading-relaxed">${escapeHtml(message)}</div>
    `;
    stack.appendChild(item);

    const remove = () => {
      if (item.parentNode) item.parentNode.removeChild(item);
    };
    item.addEventListener("click", remove);
    setTimeout(remove, 4200);
  }

  /* ---------- 2. 深色 / 浅色主题切换与记忆 ---------- */
  function initThemeToggle() {
    const btn = document.getElementById("btn-theme-toggle");
    const sun = document.getElementById("icon-theme-sun");
    const moon = document.getElementById("icon-theme-moon");
    const label = document.getElementById("label-theme-toggle");

    function syncThemeUI() {
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      if (sun && moon) {
        if (current === "dark") {
          sun.classList.remove("hidden");
          moon.classList.add("hidden");
          if (label) label.textContent = "浅色";
        } else {
          sun.classList.add("hidden");
          moon.classList.remove("hidden");
          if (label) label.textContent = "深色";
        }
      }
    }

    syncThemeUI();
    if (!btn) return;

    btn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try {
        localStorage.setItem("yingku_theme", next);
      } catch (_e) {
        /* ignore */
      }
      syncThemeUI();
      showToast(`已切换为${next === "light" ? "浅色" : "深色"}主题`, "info");
    });
  }

  /* ---------- 3. 手机端折叠菜单与通用模态框 ---------- */
  function initMobileNavAndModals() {
    const mobileBtn = document.getElementById("btn-mobile-menu");
    const drawer = document.getElementById("mobile-nav-drawer");
    if (mobileBtn && drawer) {
      mobileBtn.addEventListener("click", () => {
        const isHidden = drawer.classList.toggle("hidden");
        mobileBtn.setAttribute("aria-expanded", isHidden ? "false" : "true");
      });
    }

    document.addEventListener("click", (e) => {
      const closeBtn = e.target.closest("[data-close-modal]");
      if (closeBtn) {
        const id = closeBtn.getAttribute("data-close-modal");
        const modal = document.getElementById(id);
        if (modal) modal.classList.add("hidden");
        return;
      }
      if (e.target.classList && e.target.classList.contains("modal-backdrop")) {
        e.target.classList.add("hidden");
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        document.querySelectorAll(".modal-backdrop:not(.hidden)").forEach((m) => m.classList.add("hidden"));
      }
    });
  }

  /* ---------- 4. 首页大图轮播与横向轨道滚动 ---------- */
  function initHeroAndRails() {
    const hero = document.getElementById("hero-carousel");
    if (hero) {
      const slides = Array.from(hero.querySelectorAll("[data-hero-slide]"));
      const dots = Array.from(hero.querySelectorAll("[data-hero-dot]"));
      let currentIdx = 0;
      let timer = null;

      function goToSlide(index) {
        if (!slides.length) return;
        currentIdx = (index + slides.length) % slides.length;
        slides.forEach((sl, idx) => {
          const active = idx === currentIdx;
          sl.classList.toggle("is-active", active);
          sl.setAttribute("aria-hidden", active ? "false" : "true");
        });
        dots.forEach((dot, idx) => {
          const active = idx === currentIdx;
          dot.classList.toggle("w-6", active);
          dot.classList.toggle("bg-white", active);
          dot.classList.toggle("w-1.5", !active);
          dot.classList.toggle("bg-white/45", !active);
        });
      }

      function startAuto() {
        stopAuto();
        if (slides.length <= 1 || prefersReducedMotion()) return;
        timer = setInterval(() => goToSlide(currentIdx + 1), 6500);
      }

      function stopAuto() {
        if (timer) {
          clearInterval(timer);
          timer = null;
        }
      }

      const prevBtn = hero.querySelector("[data-hero-prev]");
      const nextBtn = hero.querySelector("[data-hero-next]");
      if (prevBtn) prevBtn.addEventListener("click", () => { goToSlide(currentIdx - 1); startAuto(); });
      if (nextBtn) nextBtn.addEventListener("click", () => { goToSlide(currentIdx + 1); startAuto(); });
      dots.forEach((d) => {
        d.addEventListener("click", () => {
          goToSlide(Number(d.getAttribute("data-hero-dot") || 0));
          startAuto();
        });
      });

      hero.addEventListener("mouseenter", stopAuto);
      hero.addEventListener("mouseleave", startAuto);
      hero.addEventListener("focusin", stopAuto);
      hero.addEventListener("focusout", startAuto);
      startAuto();
    }

    document.querySelectorAll("[data-rail-prev]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const rail = document.getElementById(btn.getAttribute("data-rail-prev"));
        if (rail) {
          rail.scrollBy({
            left: -Math.max(280, rail.clientWidth * 0.78),
            behavior: prefersReducedMotion() ? "auto" : "smooth",
          });
        }
      });
    });

    document.querySelectorAll("[data-rail-next]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const rail = document.getElementById(btn.getAttribute("data-rail-next"));
        if (rail) {
          rail.scrollBy({
            left: Math.max(280, rail.clientWidth * 0.78),
            behavior: prefersReducedMotion() ? "auto" : "smooth",
          });
        }
      });
    });
  }

  /* ---------- 5. MPC-HC 播放拉起与观看进度更新 ---------- */
  function initPlaybackAndProgress() {
    async function triggerPlay(workId, episodeId, fileId) {
      showToast("正在请求本机播放器拉起流媒体...", "info");
      const { ok, data } = await apiJson("/api/play", {
        method: "POST",
        body: {
          work_id: Number(workId),
          episode_id: episodeId ? Number(episodeId) : null,
          file_id: fileId ? Number(fileId) : null,
        },
      });
      if (!ok) {
        showToast(data.message || "拉起播放器失败，请检查设置页播放器路径与 AList 状态", "error");
        return;
      }

      const info = data.data || {};
      const label = info.episode_label ? `${info.work_title} (${info.episode_label})` : info.work_title;
      showToast(`已启动 ${info.player_name} 播放：${label}`, "ok");

      // 若当前在剧集详情页，立即更新该集进度条与状态徽标
      if (info.episode_id && info.progress) {
        updateEpisodeProgressDOM(info.episode_id, info.progress);
      }
    }

    function updateEpisodeProgressDOM(epId, prog) {
      const bar = document.querySelector(`[data-ep-progress-bar="${epId}"]`);
      const txt = document.querySelector(`[data-ep-status-text="${epId}"]`);
      const watchBtn = document.querySelector(`[data-toggle-watched][data-episode-id="${epId}"]`);
      const pct = Math.round(Number(prog.progress_percent || 0));
      const isWatched = Boolean(prog.watched);

      if (bar) bar.style.width = `${isWatched ? 100 : pct}%`;
      if (txt) txt.textContent = isWatched ? "已看完" : pct > 0 ? `已看 ${pct}%` : "点击播放";
      if (watchBtn) {
        watchBtn.setAttribute("data-current-watched", isWatched ? "1" : "0");
        watchBtn.textContent = isWatched ? "✓ 已看" : "标为已看";
      }
    }

    // 电影详情页多版本切换与播放
    const versionBtns = Array.from(document.querySelectorAll("[data-movie-version-btn]"));
    const mainMoviePlayBtn = document.getElementById("btn-play-selected-movie");
    if (versionBtns.length && mainMoviePlayBtn) {
      versionBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
          const fid = btn.getAttribute("data-movie-version-btn");
          mainMoviePlayBtn.setAttribute("data-selected-file-id", fid);
          versionBtns.forEach((b) => {
            const selected = b === btn;
            b.className = selected
              ? "px-3.5 py-1.5 rounded-full text-xs font-semibold border transition cursor-pointer bg-white text-black border-white"
              : "px-3.5 py-1.5 rounded-full text-xs font-semibold border transition cursor-pointer bg-white/10 text-white border-white/25 hover:bg-white/20";
          });
        });
      });
    }

    if (mainMoviePlayBtn) {
      mainMoviePlayBtn.addEventListener("click", () => {
        const wid = mainMoviePlayBtn.getAttribute("data-work-id");
        const fid = mainMoviePlayBtn.getAttribute("data-selected-file-id");
        triggerPlay(wid, null, fid || null);
      });
    }

    // 全局代理点击播放按钮、标记已看/未看、单集半程进度与快速绑定
    document.addEventListener("click", async (e) => {
      const playTrigger = e.target.closest("[data-play-work]");
      if (playTrigger && !e.target.closest("[data-toggle-watched]") && !e.target.closest("[data-ep-half-progress]")) {
        e.preventDefault();
        e.stopPropagation();
        const wid = playTrigger.getAttribute("data-play-work");
        const eid = playTrigger.getAttribute("data-play-episode");
        const fid = playTrigger.getAttribute("data-play-file");
        await triggerPlay(wid, eid, fid);
        return;
      }

      const watchBtn = e.target.closest("[data-toggle-watched]");
      if (watchBtn) {
        e.preventDefault();
        const wid = watchBtn.getAttribute("data-work-id");
        const eid = watchBtn.getAttribute("data-episode-id");
        const curWatched = watchBtn.getAttribute("data-current-watched") === "1";
        const nextWatched = !curWatched;

        const { ok, data } = await apiJson("/api/progress", {
          method: "POST",
          body: {
            work_id: Number(wid),
            episode_id: eid ? Number(eid) : null,
            watched: nextWatched,
          },
        });
        if (!ok) {
          showToast(data.message || "更新观看状态失败", "error");
          return;
        }
        showToast(nextWatched ? "已标记为已看" : "已重置为未看", "ok");
        if (eid && data.progress) {
          updateEpisodeProgressDOM(eid, data.progress);
        } else {
          window.location.reload();
        }
        return;
      }

      const halfBtn = e.target.closest("[data-ep-half-progress]");
      if (halfBtn) {
        e.preventDefault();
        const eid = halfBtn.getAttribute("data-ep-half-progress");
        const wid = halfBtn.getAttribute("data-work-id");
        const { ok, data } = await apiJson("/api/progress", {
          method: "POST",
          body: {
            work_id: Number(wid),
            episode_id: Number(eid),
            watched: false,
            progress_percent: 50,
          },
        });
        if (ok && data.progress) {
          updateEpisodeProgressDOM(eid, data.progress);
          showToast("已记录该集观看进度至 50%", "ok");
        }
        return;
      }

      const bindBtn = e.target.closest("[data-quick-bind-file]");
      if (bindBtn) {
        const fid = bindBtn.getAttribute("data-quick-bind-file");
        const wid = bindBtn.getAttribute("data-work-id");
        const sInput = document.querySelector(`[data-bind-season="${fid}"]`);
        const eInput = document.querySelector(`[data-bind-episode="${fid}"]`);
        const sVal = sInput ? sInput.value : "";
        const eVal = eInput ? eInput.value : "";
        if (!eVal) {
          showToast("请填写对应的集号", "warn");
          return;
        }
        const { ok, data } = await apiJson(`/api/admin/works/${wid}/map-episode`, {
          method: "POST",
          body: { file_id: Number(fid), season_number: Number(sVal || 1), episode_number: Number(eVal) },
        });
        if (!ok) {
          showToast(data.message || "绑定集号失败", "error");
          return;
        }
        showToast("已绑定到对应单集，正在刷新...", "ok");
        setTimeout(() => window.location.reload(), 450);
      }
    });

    // 支持键盘回车播放剧集剧照卡片
    document.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.matches("[data-play-work][role='button']")) {
        e.preventDefault();
        e.target.click();
      }
    });
  }

  /* ---------- 6. 首次引导向导与系统设置页 ---------- */
  function collectFormValues(formEl) {
    const out = {};
    if (!formEl) return out;
    formEl.querySelectorAll("input[name], select[name]").forEach((el) => {
      out[el.name] = el.value;
    });
    return out;
  }

  function applyServiceCheckUI(sid, state, badgeText, message) {
    document.querySelectorAll(`[data-status-badge="${sid}"]`).forEach((b) => {
      b.setAttribute("data-state", state);
      b.textContent = badgeText;
    });
    document.querySelectorAll(`[data-step-dot="${sid}"]`).forEach((dot) => {
      dot.style.backgroundColor =
        state === "ok"
          ? "var(--status-ok-fg)"
          : state === "error"
          ? "var(--status-err-fg)"
          : state === "skipped"
          ? "var(--status-warn-fg)"
          : "var(--text-muted)";
    });
    document.querySelectorAll(`[data-check-feedback="${sid}"]`).forEach((box) => {
      if (message) {
        box.textContent = message;
        box.classList.remove("hidden");
        box.style.color =
          state === "ok"
            ? "var(--status-ok-fg)"
            : state === "error"
            ? "var(--status-err-fg)"
            : "var(--text-secondary)";
      }
    });
  }

  function initSetupAndSettings() {
    const wizardRoot = document.getElementById("setup-wizard-root");
    const setupForm = document.getElementById("setup-config-form");
    const settingsForm = document.getElementById("settings-config-form");
    const activeForm = setupForm || settingsForm;
    if (!activeForm) return;

    const skippedServices = {};

    // 引导步骤切换
    if (wizardRoot) {
      const tabs = Array.from(wizardRoot.querySelectorAll("[data-wizard-tab]"));
      const panels = Array.from(wizardRoot.querySelectorAll("[data-wizard-panel]"));

      function showStep(stepNum) {
        tabs.forEach((t) => {
          const isCur = Number(t.getAttribute("data-wizard-tab")) === Number(stepNum);
          t.style.borderColor = isCur ? "var(--accent)" : "var(--border-subtle)";
          t.style.backgroundColor = isCur ? "var(--bg-elevated)" : "var(--bg-surface)";
        });
        panels.forEach((p) => {
          const isCur = Number(p.getAttribute("data-wizard-panel")) === Number(stepNum);
          p.classList.toggle("hidden", !isCur);
        });
      }

      showStep(1);
      tabs.forEach((t) =>
        t.addEventListener("click", () => showStep(Number(t.getAttribute("data-wizard-tab"))))
      );
      wizardRoot.querySelectorAll("[data-wizard-prev]").forEach((btn) =>
        btn.addEventListener("click", () => showStep(Number(btn.getAttribute("data-wizard-prev")) - 1))
      );
      wizardRoot.querySelectorAll("[data-wizard-next]").forEach((btn) =>
        btn.addEventListener("click", () => showStep(Number(btn.getAttribute("data-wizard-next")) + 1))
      );

      // 选填步骤“跳过此步”
      wizardRoot.querySelectorAll("[data-skip-service]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const sid = btn.getAttribute("data-skip-service");
          const nextStep = Number(btn.getAttribute("data-next-step") || 5);
          skippedServices[sid] = true;
          // 如果输入框当前是占位符如 to_do，不强制改动，但标记跳过
          applyServiceCheckUI(
            sid,
            "skipped",
            "已跳过（降级运行）",
            sid === "deepseek"
              ? "已跳过 DeepSeek 配置：网站将使用本地规则与防和谐词典识别片名，后续可在“设置”页随时补填。"
              : "已跳过 MDBList 配置：网站将展示 TMDB 官方评分，后续可在“设置”页随时补填。"
          );
          showToast("已跳过该选填服务，启用平滑降级模式", "info");
          showStep(nextStep);
        });
      });

      const finishBtn = document.getElementById("btn-finish-setup");
      if (finishBtn) {
        finishBtn.addEventListener("click", async () => {
          finishBtn.disabled = true;
          const origText = finishBtn.textContent;
          finishBtn.textContent = "正在验证必需项并保存...";
          const values = collectFormValues(setupForm);
          const { ok, data } = await apiJson("/api/setup/save", {
            method: "POST",
            body: {
              values,
              skipped: skippedServices,
              complete_onboarding: true,
              verify_required: true,
            },
          });
          finishBtn.disabled = false;
          finishBtn.textContent = origText;

          if (!ok) {
            showToast(data.message || "保存引导配置未通过，请检查 AList 与 TMDB 密钥", "error");
            return;
          }
          showToast("配置验证通过，正在进入影库首页...", "ok");
          window.location.href = data.redirect || "/";
        });
      }
    }

    // 单项“检测”按钮（引导页与设置页通用）
    activeForm.querySelectorAll("[data-check-service]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const sid = btn.getAttribute("data-check-service");
        const orig = btn.textContent;
        btn.disabled = true;
        btn.textContent = "检测中...";

        const values = collectFormValues(activeForm);
        const { data } = await apiJson("/api/setup/check", {
          method: "POST",
          body: { service: sid, values },
        });

        btn.disabled = false;
        btn.textContent = orig;

        if (data.ok) {
          skippedServices[sid] = false;
          applyServiceCheckUI(sid, "ok", "已连接", data.message);
          showToast(`${sid.toUpperCase()} 检测通过`, "ok");
        } else {
          applyServiceCheckUI(sid, "error", "检测未通过", data.message || "连接失败");
          showToast(data.message || "检测未通过", "warn");
        }
      });
    });

    // 设置页：保存全部设置 & 一键检测全部
    const saveSettingsBtn = document.getElementById("btn-save-settings");
    if (saveSettingsBtn && settingsForm) {
      saveSettingsBtn.addEventListener("click", async () => {
        saveSettingsBtn.disabled = true;
        const values = collectFormValues(settingsForm);
        const { ok, data } = await apiJson("/api/settings/save", {
          method: "POST",
          body: { values, verify_required: false },
        });
        saveSettingsBtn.disabled = false;
        if (!ok) {
          showToast(data.message || "保存设置失败", "error");
          return;
        }
        if (data.statuses) {
          Object.entries(data.statuses).forEach(([sid, st]) => {
            applyServiceCheckUI(sid, st.state, st.label, st.message);
          });
        }
        showToast(data.message || "设置已写回 .env 并立即生效", "ok");
      });
    }

    const checkAllBtn = document.getElementById("btn-check-all-services");
    if (checkAllBtn && settingsForm) {
      checkAllBtn.addEventListener("click", async () => {
        checkAllBtn.disabled = true;
        const orig = checkAllBtn.textContent;
        checkAllBtn.textContent = "正在逐项检测...";
        await apiJson("/api/settings/save", {
          method: "POST",
          body: { values: collectFormValues(settingsForm), verify_required: false },
        });
        const { ok, data } = await apiJson("/api/settings/check-all", { method: "POST", body: {} });
        checkAllBtn.disabled = false;
        checkAllBtn.textContent = orig;
        if (ok && data.statuses) {
          Object.entries(data.statuses).forEach(([sid, st]) => {
            applyServiceCheckUI(sid, st.state, st.label, st.message);
          });
          showToast("全部外部服务状态检测完毕", "ok");
        }
      });
    }
  }

  /* ---------- 7. 添加影视页：网盘浏览、防和谐验证台、分桶确认与入库进度 ---------- */
  function renderTraceStepsHtml(rec) {
    const matched = rec.matched_work;
    const matchedLabel = matched
      ? `《${escapeHtml(matched.title)}》${matched.year ? ` (${matched.year})` : ""} · ${
          matched.media_type === "tv" ? "剧集" : "电影"
        } · TMDB #${matched.tmdb_id}`
      : "未找到高置信度匹配（可手动搜索指定）";

    const seTag =
      rec.season_number != null && rec.episode_number != null
        ? ` · S${String(rec.season_number).padStart(2, "0")}E${String(rec.episode_number).padStart(2, "0")}`
        : "";

    const rulesBadges = (rec.applied_rules || [])
      .map(
        (r) =>
          `<span class="px-2 py-0.5 rounded text-[11px]" style="background: var(--bg-elevated); color: var(--text-secondary);">${escapeHtml(
            r
          )}</span>`
      )
      .join(" ");

    return `
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div class="flex items-center gap-1.5">
          <span class="status-pill" data-state="${
            rec.bucket === "confirmable" ? "ok" : rec.bucket === "needs_review" ? "pending" : "error"
          }">${escapeHtml(rec.bucket_label || "待确认")}</span>
          <span class="px-2 py-0.5 rounded-full text-[11px]" style="background: var(--bg-elevated); color: var(--text-secondary);">
            ${escapeHtml(rec.source_label || "规则识别")}${rec.from_cache ? " · 命中本地识别缓存" : ""}
          </span>
        </div>
        <span class="text-[11px] font-mono" style="color: var(--text-muted);">置信度 ${Math.round(
          Number(rec.confidence || 0) * 100
        )}%</span>
      </div>

      <div class="grid grid-cols-1 gap-2 text-xs">
        <div class="p-2.5 rounded-lg" style="background: var(--bg-surface); border: 1px solid var(--border-subtle);">
          <div class="text-[11px]" style="color: var(--text-muted);">① 原始文件名</div>
          <div class="font-mono font-medium break-all mt-0.5">${escapeHtml(rec.raw_name)}</div>
        </div>
        <div class="p-2.5 rounded-lg" style="background: var(--bg-surface); border: 1px solid var(--border-subtle);">
          <div class="text-[11px]" style="color: var(--text-muted);">② 规则清洗后名称</div>
          <div class="font-medium mt-0.5">${escapeHtml(rec.cleaned_name)}${rec.year ? ` (${rec.year})` : ""}${escapeHtml(seTag)}</div>
        </div>
        <div class="p-2.5 rounded-lg" style="background: var(--bg-surface); border: 1px solid var(--border-subtle);">
          <div class="text-[11px]" style="color: var(--text-muted);">③ 推测的原始片名</div>
          <div class="font-bold mt-0.5">${escapeHtml(rec.inferred_title)}${
      rec.secondary_title ? ` / ${escapeHtml(rec.secondary_title)}` : ""
    }</div>
        </div>
        <div class="p-2.5 rounded-lg" style="background: var(--bg-surface); border: 1px solid var(--border-subtle);">
          <div class="text-[11px]" style="color: var(--text-muted);">④ 匹配到的 TMDB 作品（经检索校验）</div>
          <div class="font-bold mt-0.5">${matchedLabel}</div>
        </div>
      </div>

      ${rulesBadges ? `<div class="flex flex-wrap gap-1.5">${rulesBadges}</div>` : ""}

      <div class="text-xs leading-relaxed p-3 rounded-lg" style="background: var(--bg-surface); color: var(--text-secondary); border: 1px solid var(--border-subtle);">
        <strong>判断理由：</strong>${escapeHtml(rec.reasoning || "")}
      </div>
    `;
  }

  function initImportPage() {
    const root = document.getElementById("import-page-root");
    if (!root) return;

    let currentDir = "/";
    let currentEntries = [];
    const selectedPaths = new Set();
    const filenameOverrides = {};

    let recognizedItems = [];
    let activeBucket = "all";
    let editingItemIndex = null;

    const bcNav = document.getElementById("alist-breadcrumbs");
    const entryList = document.getElementById("alist-entry-list");
    const countLabel = document.getElementById("alist-selected-count");
    const startScanBtn = document.getElementById("btn-start-scan");

    function updateSelectedCount() {
      if (countLabel) countLabel.textContent = `已勾选 ${selectedPaths.size} 个文件或文件夹`;
      if (startScanBtn) startScanBtn.disabled = selectedPaths.size === 0;
    }

    async function loadDirectory(path, refresh = false) {
      currentDir = path || "/";
      if (entryList) {
        entryList.innerHTML = `<div class="p-8 text-center text-xs" style="color: var(--text-muted);">正在读取 ${escapeHtml(
          currentDir
        )} ...</div>`;
      }
      const { ok, data } = await apiJson(
        `/api/import/browse?path=${encodeURIComponent(currentDir)}&refresh=${refresh ? "1" : "0"}`
      );
      if (!ok) {
        if (entryList) {
          entryList.innerHTML = `<div class="p-8 text-center text-xs" style="color: var(--status-err-fg);">${escapeHtml(
            data.message || "读取 AList 目录失败"
          )}</div>`;
        }
        return;
      }

      const payload = data.data || {};
      currentEntries = payload.entries || [];

      if (bcNav) {
        bcNav.innerHTML = (payload.breadcrumbs || [])
          .map(
            (b, i, arr) => `
            <button type="button" data-bc-path="${escapeHtml(b.path)}" class="btn-ghost !py-1 !px-2 text-xs ${
              i === arr.length - 1 ? "font-bold" : ""
            }">${escapeHtml(b.name)}</button>
            ${i < arr.length - 1 ? `<span style="color: var(--text-muted);">/</span>` : ""}
          `
          )
          .join("");
      }

      if (!currentEntries.length) {
        entryList.innerHTML = `<div class="p-8 text-center text-xs" style="color: var(--text-muted);">此目录为空</div>`;
        return;
      }

      entryList.innerHTML = currentEntries
        .map((it) => {
          const selectable = it.is_dir || it.is_video;
          const checked = selectedPaths.has(it.path) ? "checked" : "";
          const aliasNote = filenameOverrides[it.path]
            ? `<div class="text-[11px] mt-0.5" style="color: var(--status-warn-fg);">模拟改写名：${escapeHtml(
                filenameOverrides[it.path]
              )}</div>`
            : "";

          return `
            <div class="px-3.5 py-2.5 flex items-center justify-between gap-3 hover:opacity-95" style="border-color: var(--border-subtle);">
              <div class="flex items-center gap-3 min-w-0 flex-1">
                ${
                  selectable
                    ? `<input type="checkbox" data-alist-check="${escapeHtml(it.path)}" ${checked} class="w-4 h-4 shrink-0 cursor-pointer" />`
                    : `<span class="w-4 h-4 shrink-0"></span>`
                }
                <div class="min-w-0 flex-1">
                  ${
                    it.is_dir
                      ? `<button type="button" data-open-dir="${escapeHtml(
                          it.path
                        )}" class="text-left text-xs sm:text-sm font-semibold hover:underline truncate block w-full bg-transparent border-0 p-0 cursor-pointer" style="color: var(--text-primary);">📁 ${escapeHtml(
                          it.name
                        )}</button>`
                      : `<div class="text-xs sm:text-sm ${
                          it.is_video ? "font-medium" : "opacity-50"
                        } truncate" title="${escapeHtml(it.name)}">${it.is_video ? "🎬" : "📄"} ${escapeHtml(
                          it.name
                        )}</div>`
                  }
                  ${aliasNote}
                </div>
              </div>
              <div class="flex items-center gap-2 shrink-0 text-xs" style="color: var(--text-muted);">
                ${
                  it.already_imported
                    ? `<span class="status-pill !py-0 !px-2 !text-[10px]" data-state="ok">已入库</span>`
                    : ""
                }
                ${
                  it.is_video
                    ? `<button type="button" data-alias-path="${escapeHtml(
                        it.path
                      )}" data-orig-name="${escapeHtml(
                        it.name
                      )}" class="btn-ghost !py-0.5 !px-2 !text-[11px]" title="模拟网盘防和谐改写文件名测试还原入库">模拟改名</button>`
                    : ""
                }
                <span>${escapeHtml(it.size_human || (it.is_dir ? "文件夹" : ""))}</span>
              </div>
            </div>
          `;
        })
        .join("");
    }

    if (bcNav) {
      bcNav.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-bc-path]");
        if (btn) loadDirectory(btn.getAttribute("data-bc-path"));
      });
    }

    if (entryList) {
      entryList.addEventListener("click", (e) => {
        const dirBtn = e.target.closest("[data-open-dir]");
        if (dirBtn) {
          loadDirectory(dirBtn.getAttribute("data-open-dir"));
          return;
        }
        const aliasBtn = e.target.closest("[data-alias-path]");
        if (aliasBtn) {
          const p = aliasBtn.getAttribute("data-alias-path");
          const orig = aliasBtn.getAttribute("data-orig-name");
          const nextName = window.prompt(
            "输入模拟的防和谐改写文件名（仅用于本次识别还原演示，不会改动网盘真实文件）：",
            filenameOverrides[p] || `【先转存防和谐】肖·shen·克·的·jiu·赎.1994.4K.mp4`
          );
          if (nextName !== null) {
            const trimmed = nextName.trim();
            if (trimmed && trimmed !== orig) {
              filenameOverrides[p] = trimmed;
              selectedPaths.add(p);
            } else {
              delete filenameOverrides[p];
            }
            updateSelectedCount();
            loadDirectory(currentDir);
          }
        }
      });

      entryList.addEventListener("change", (e) => {
        const cb = e.target.closest("[data-alist-check]");
        if (!cb) return;
        const p = cb.getAttribute("data-alist-check");
        if (cb.checked) selectedPaths.add(p);
        else selectedPaths.delete(p);
        updateSelectedCount();
      });
    }

    const refreshBtn = document.getElementById("btn-alist-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", () => loadDirectory(currentDir, true));

    const selectAllDirBtn = document.getElementById("btn-alist-select-videos");
    if (selectAllDirBtn) {
      selectAllDirBtn.addEventListener("click", () => {
        currentEntries.forEach((it) => {
          if (it.is_dir || it.is_video) selectedPaths.add(it.path);
        });
        updateSelectedCount();
        entryList.querySelectorAll("[data-alist-check]").forEach((cb) => {
          cb.checked = true;
        });
      });
    }

    // 右侧：防和谐改写文件名验证台
    const sampleFilenameInput = document.getElementById("sample-filename-input");
    const sampleParentInput = document.getElementById("sample-parent-input");
    const sampleResultCard = document.getElementById("sample-result-card");
    const runSampleBtn = document.getElementById("btn-run-sample-recognize");

    document.querySelectorAll("[data-sample-filename]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (sampleFilenameInput) sampleFilenameInput.value = btn.getAttribute("data-sample-filename") || "";
        if (sampleParentInput) sampleParentInput.value = btn.getAttribute("data-sample-parent") || "/";
        if (runSampleBtn) runSampleBtn.click();
      });
    });

    if (runSampleBtn) {
      runSampleBtn.addEventListener("click", async () => {
        const filename = sampleFilenameInput ? sampleFilenameInput.value.trim() : "";
        const parent_path = sampleParentInput ? sampleParentInput.value.trim() : "/";
        if (!filename) {
          showToast("请输入要验证的网盘文件名", "warn");
          return;
        }
        runSampleBtn.disabled = true;
        const origText = runSampleBtn.textContent;
        runSampleBtn.textContent = "正在清洗还原并向 TMDB 校验...";

        const { ok, data } = await apiJson("/api/import/recognize-sample", {
          method: "POST",
          body: { filename, parent_path, use_cache: true },
        });

        runSampleBtn.disabled = false;
        runSampleBtn.textContent = origText;

        if (!ok || !data.result) {
          showToast(data.message || "识别测试失败", "error");
          return;
        }
        if (sampleResultCard) {
          sampleResultCard.innerHTML = renderTraceStepsHtml(data.result);
          sampleResultCard.classList.remove("hidden");
        }
      });
    }

    // 后台任务轮询进度条
    const taskBanner = document.getElementById("import-task-banner");
    const taskSummary = document.getElementById("import-task-summary");
    const taskPercent = document.getElementById("import-task-percent");
    const taskBar = document.getElementById("import-task-bar");
    const taskSpinner = document.getElementById("import-task-spinner");
    const taskActions = document.getElementById("import-task-actions");

    function pollTaskUntilDone(taskId, onDone) {
      if (taskBanner) taskBanner.classList.remove("hidden");
      if (taskActions) taskActions.classList.add("hidden");
      if (taskSpinner) taskSpinner.classList.remove("hidden");

      const tick = async () => {
        const { ok, data } = await apiJson(`/api/tasks/${encodeURIComponent(taskId)}`);
        if (!ok || !data.task) {
          showToast("查询后台任务进度失败", "error");
          return;
        }
        const t = data.task;
        if (taskSummary) taskSummary.textContent = t.summary || "处理中...";
        if (taskPercent) taskPercent.textContent = `${t.percent || 0}%`;
        if (taskBar) taskBar.style.width = `${t.percent || 0}%`;

        if (t.status === "completed") {
          if (taskSpinner) taskSpinner.classList.add("hidden");
          onDone(t);
        } else if (t.status === "failed") {
          if (taskSpinner) taskSpinner.classList.add("hidden");
          showToast(t.error || t.summary || "任务执行失败", "error");
        } else {
          setTimeout(tick, 550);
        }
      };
      tick();
    }

    // 扫描识别并渲染三类分桶结果
    const resultsSection = document.getElementById("scan-results-section");
    const recListEl = document.getElementById("recognized-items-list");

    function refreshBucketCountsAndRender() {
      const counts = { all: recognizedItems.length, confirmable: 0, needs_review: 0, unrecognized: 0 };
      recognizedItems.forEach((it) => {
        counts[it.bucket] = (counts[it.bucket] || 0) + 1;
      });
      Object.entries(counts).forEach(([k, v]) => {
        document.querySelectorAll(`[data-bucket-count="${k}"]`).forEach((el) => (el.textContent = String(v)));
      });

      const visible = recognizedItems
        .map((it, idx) => ({ it, idx }))
        .filter(({ it }) => activeBucket === "all" || it.bucket === activeBucket);

      if (!visible.length) {
        recListEl.innerHTML = `<div class="p-8 text-center text-xs rounded-xl border" style="border-color: var(--border-subtle); color: var(--text-muted);">当前分桶下没有条目</div>`;
        return;
      }

      recListEl.innerHTML = visible
        .map(({ it, idx }) => {
          const mw = it.matched_work;
          const canImport = Boolean(mw && mw.tmdb_id);
          const posterSrc = mw && mw.poster_local ? mediaImgUrl(mw.poster_local) : "";
          const stateAttr =
            it.bucket === "confirmable" ? "ok" : it.bucket === "needs_review" ? "pending" : "error";

          return `
            <div class="p-4 rounded-xl border flex flex-col lg:flex-row lg:items-center justify-between gap-4" style="border-color: var(--border-subtle); background: var(--bg-subtle);">
              <div class="flex items-start gap-3.5 min-w-0 flex-1">
                <input
                  type="checkbox"
                  data-rec-check="${idx}"
                  ${it._checked && canImport ? "checked" : ""}
                  ${canImport ? "" : "disabled"}
                  class="w-4 h-4 mt-1 shrink-0 cursor-pointer"
                />
                <div class="w-12 h-16 rounded-lg overflow-hidden shrink-0 hidden sm:flex items-center justify-center text-[10px]" style="background: var(--bg-elevated); color: var(--text-muted);">
                  ${
                    posterSrc
                      ? `<img src="${escapeHtml(posterSrc)}" alt="" class="w-full h-full object-cover" />`
                      : `<span>${mw ? escapeHtml(mw.media_type === "tv" ? "剧集" : "电影") : "未匹配"}</span>`
                  }
                </div>
                <div class="min-w-0 flex-1 space-y-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="status-pill !py-0.5 !px-2 !text-[11px]" data-state="${stateAttr}">${escapeHtml(
            it.bucket_label
          )}</span>
                    <span class="text-xs font-mono truncate" style="color: var(--text-secondary);" title="${escapeHtml(
                      it.raw_name
                    )}">${escapeHtml(it.raw_name)}</span>
                    <span class="text-[11px]" style="color: var(--text-muted);">(${escapeHtml(it.size_human || "")})</span>
                  </div>

                  <div class="text-xs sm:text-sm">
                    <span style="color: var(--text-muted);">识别链路：</span>
                    <span>${escapeHtml(it.cleaned_name)}</span>
                    <span style="color: var(--text-muted);"> → </span>
                    <span class="font-medium">${escapeHtml(it.inferred_title)}</span>
                    <span style="color: var(--text-muted);"> → </span>
                    ${
                      mw
                        ? `<strong style="color: var(--text-primary);">《${escapeHtml(mw.title)}》${
                            mw.year ? ` (${mw.year})` : ""
                          } [${mw.media_type === "tv" ? "剧集" : "电影"}]</strong>`
                        : `<span style="color: var(--status-err-fg);">未匹配到 TMDB 作品（请点击右侧手动指定）</span>`
                    }
                  </div>

                  <div class="text-[11px] line-clamp-1" style="color: var(--text-muted);">${escapeHtml(
                    it.reasoning || ""
                  )}</div>
                </div>
              </div>

              <div class="flex flex-wrap items-center gap-2 shrink-0 pl-7 lg:pl-0">
                ${
                  (mw ? mw.media_type : it.media_type) === "tv"
                    ? `
                  <div class="flex items-center gap-1 text-xs">
                    <span>S</span>
                    <input type="number" min="0" max="99" value="${
                      it.season_number != null ? it.season_number : 1
                    }" data-rec-season="${idx}" class="form-input !w-14 !py-1 !px-1.5 text-xs text-center" />
                    <span>E</span>
                    <input type="number" min="1" max="999" value="${
                      it.episode_number != null ? it.episode_number : ""
                    }" placeholder="集" data-rec-episode="${idx}" class="form-input !w-14 !py-1 !px-1.5 text-xs text-center" />
                  </div>
                `
                    : `
                  <input type="text" value="${escapeHtml(
                    it.version_label || "标准版"
                  )}" data-rec-version="${idx}" placeholder="版本名" class="form-input !w-28 !py-1 !px-2 text-xs" />
                `
                }

                <button type="button" data-open-trace="${idx}" class="btn-ghost !py-1 !px-2.5 text-xs">识别详情</button>
                <button type="button" data-open-tmdb-picker="${idx}" class="btn-secondary !py-1 !px-3 text-xs">手动指定 TMDB</button>
              </div>
            </div>
          `;
        })
        .join("");
    }

    if (startScanBtn) {
      startScanBtn.addEventListener("click", async () => {
        const paths = Array.from(selectedPaths);
        if (!paths.length) return;
        startScanBtn.disabled = true;
        const { ok, data } = await apiJson("/api/import/scan", {
          method: "POST",
          body: { paths, filename_overrides: filenameOverrides },
        });
        startScanBtn.disabled = false;
        if (!ok || !data.task_id) {
          showToast(data.message || "启动扫描任务失败", "error");
          return;
        }

        pollTaskUntilDone(data.task_id, (task) => {
          const res = task.result || {};
          recognizedItems = (res.items || []).map((item) =>
            Object.assign({}, item, {
              _checked: item.bucket === "confirmable" && Boolean(item.matched_work),
            })
          );
          if (resultsSection) resultsSection.classList.remove("hidden");
          activeBucket = "all";
          refreshBucketCountsAndRender();
          if (resultsSection) resultsSection.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth" });
        });
      });
    }

    // 分桶标签切换
    document.querySelectorAll("[data-bucket-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeBucket = btn.getAttribute("data-bucket-tab") || "all";
        document.querySelectorAll("[data-bucket-tab]").forEach((b) => {
          const active = b === btn;
          b.className = `${active ? "btn-primary" : "btn-secondary"} !py-1 !px-3.5 text-xs`;
        });
        refreshBucketCountsAndRender();
      });
    });

    // 列表内部事件委托（勾选、修改季集、查看识别详情、手动指定 TMDB）
    if (recListEl) {
      recListEl.addEventListener("change", (e) => {
        const cb = e.target.closest("[data-rec-check]");
        if (cb) {
          const idx = Number(cb.getAttribute("data-rec-check"));
          if (recognizedItems[idx]) recognizedItems[idx]._checked = cb.checked;
          return;
        }
        const sIn = e.target.closest("[data-rec-season]");
        if (sIn) {
          const idx = Number(sIn.getAttribute("data-rec-season"));
          if (recognizedItems[idx]) recognizedItems[idx].season_number = sIn.value === "" ? null : Number(sIn.value);
          return;
        }
        const eIn = e.target.closest("[data-rec-episode]");
        if (eIn) {
          const idx = Number(eIn.getAttribute("data-rec-episode"));
          if (recognizedItems[idx]) recognizedItems[idx].episode_number = eIn.value === "" ? null : Number(eIn.value);
          return;
        }
        const vIn = e.target.closest("[data-rec-version]");
        if (vIn) {
          const idx = Number(vIn.getAttribute("data-rec-version"));
          if (recognizedItems[idx]) recognizedItems[idx].version_label = vIn.value.trim();
        }
      });

      recListEl.addEventListener("click", (e) => {
        const traceBtn = e.target.closest("[data-open-trace]");
        if (traceBtn) {
          const idx = Number(traceBtn.getAttribute("data-open-trace"));
          const rec = recognizedItems[idx];
          const modal = document.getElementById("modal-recognition-trace");
          const body = document.getElementById("trace-modal-body");
          if (rec && modal && body) {
            body.innerHTML = renderTraceStepsHtml(rec);
            modal.classList.remove("hidden");
          }
          return;
        }

        const pickerBtn = e.target.closest("[data-open-tmdb-picker]");
        if (pickerBtn) {
          editingItemIndex = Number(pickerBtn.getAttribute("data-open-tmdb-picker"));
          const rec = recognizedItems[editingItemIndex];
          const modal = document.getElementById("modal-tmdb-picker");
          const sub = document.getElementById("tmdb-picker-subtitle");
          const qInput = document.getElementById("tmdb-manual-query");
          if (rec && modal) {
            if (sub) sub.textContent = `当前文件：${rec.filename}`;
            if (qInput) qInput.value = rec.inferred_title || rec.cleaned_name || "";
            modal.classList.remove("hidden");
            const searchBtn = document.getElementById("btn-tmdb-manual-search");
            if (searchBtn && qInput && qInput.value.trim()) searchBtn.click();
          }
        }
      });
    }

    // 手动搜索 TMDB 模态框
    const manualSearchBtn = document.getElementById("btn-tmdb-manual-search");
    const manualQueryInput = document.getElementById("tmdb-manual-query");
    const manualTypeSelect = document.getElementById("tmdb-manual-type");
    const manualResultsEl = document.getElementById("tmdb-manual-results");

    if (manualQueryInput && manualSearchBtn) {
      manualQueryInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          manualSearchBtn.click();
        }
      });
    }

    if (manualSearchBtn && manualResultsEl) {
      manualSearchBtn.addEventListener("click", async () => {
        const q = manualQueryInput ? manualQueryInput.value.trim() : "";
        const tp = manualTypeSelect ? manualTypeSelect.value : "";
        if (!q) {
          showToast("请输入要搜索的片名关键词", "warn");
          return;
        }
        manualResultsEl.innerHTML = `<div class="p-6 text-center text-xs" style="color: var(--text-muted);">正在检索 TMDB 并缓存预览图...</div>`;
        const { ok, data } = await apiJson(
          `/api/import/tmdb-search?q=${encodeURIComponent(q)}&type=${encodeURIComponent(tp)}`
        );
        if (!ok) {
          manualResultsEl.innerHTML = `<div class="p-6 text-center text-xs" style="color: var(--status-err-fg);">${escapeHtml(
            data.message || "检索失败"
          )}</div>`;
          return;
        }
        const items = data.items || [];
        if (!items.length) {
          manualResultsEl.innerHTML = `<div class="p-6 text-center text-xs" style="color: var(--text-muted);">未找到匹配的 TMDB 影视条目</div>`;
          return;
        }
        manualResultsEl.innerHTML = items
          .map((cand, cIdx) => {
            const pUrl = cand.poster_local ? mediaImgUrl(cand.poster_local) : "";
            return `
              <div class="p-3 rounded-xl border flex items-center justify-between gap-3" style="border-color: var(--border-subtle); background: var(--bg-subtle);">
                <div class="flex items-center gap-3 min-w-0">
                  <div class="w-10 h-14 rounded overflow-hidden shrink-0" style="background: var(--bg-elevated);">
                    ${pUrl ? `<img src="${escapeHtml(pUrl)}" alt="" class="w-full h-full object-cover" />` : ""}
                  </div>
                  <div class="min-w-0">
                    <div class="text-sm font-bold truncate">${escapeHtml(cand.title)} ${
              cand.year ? `(${cand.year})` : ""
            }</div>
                    <div class="text-xs truncate" style="color: var(--text-muted);">
                      ${cand.media_type === "tv" ? "剧集" : "电影"} · TMDB #${cand.tmdb_id} · ★ ${cand.tmdb_rating || 0}
                    </div>
                    <div class="text-xs line-clamp-1 mt-0.5" style="color: var(--text-secondary);">${escapeHtml(
                      cand.overview || ""
                    )}</div>
                  </div>
                </div>
                <button type="button" data-pick-tmdb-idx="${cIdx}" class="btn-primary !py-1.5 !px-3.5 text-xs shrink-0">选定此作品</button>
              </div>
            `;
          })
          .join("");

        manualResultsEl.querySelectorAll("[data-pick-tmdb-idx]").forEach((pBtn) => {
          pBtn.addEventListener("click", () => {
            const chosen = items[Number(pBtn.getAttribute("data-pick-tmdb-idx"))];
            if (!chosen || editingItemIndex == null || !recognizedItems[editingItemIndex]) return;
            const targetItem = recognizedItems[editingItemIndex];
            const applyFolder = document.getElementById("tmdb-apply-same-folder");
            const shouldBatch = applyFolder && applyFolder.checked;

            recognizedItems.forEach((it, idx) => {
              if (idx === editingItemIndex || (shouldBatch && it.parent_path === targetItem.parent_path)) {
                it.matched_work = chosen;
                it.media_type = chosen.media_type;
                it.bucket = "confirmable";
                it.bucket_label = "可确认（手动指定）";
                it._checked = true;
                it.reasoning = `已由用户手动指定为 TMDB ${chosen.media_type === "tv" ? "剧集" : "电影"}《${
                  chosen.title
                }》(#${chosen.tmdb_id})。`;
              }
            });

            document.getElementById("modal-tmdb-picker").classList.add("hidden");
            refreshBucketCountsAndRender();
            showToast(`已指定为《${chosen.title}》`, "ok");
          });
        });
      });
    }

    // 批量勾选与确认入库
    const selConfirmBtn = document.getElementById("btn-select-confirmable");
    if (selConfirmBtn) {
      selConfirmBtn.addEventListener("click", () => {
        recognizedItems.forEach((it) => {
          it._checked = it.bucket === "confirmable" && Boolean(it.matched_work);
        });
        refreshBucketCountsAndRender();
      });
    }

    const selMatchedBtn = document.getElementById("btn-select-all-matched");
    if (selMatchedBtn) {
      selMatchedBtn.addEventListener("click", () => {
        recognizedItems.forEach((it) => {
          if (it.matched_work) it._checked = true;
        });
        refreshBucketCountsAndRender();
      });
    }

    const confirmImportBtn = document.getElementById("btn-confirm-import");
    if (confirmImportBtn) {
      confirmImportBtn.addEventListener("click", async () => {
        const chosen = recognizedItems.filter((it) => it._checked && it.matched_work && it.matched_work.tmdb_id);
        if (!chosen.length) {
          showToast("请至少勾选一项已匹配 TMDB 作品的条目再入库", "warn");
          return;
        }

        const payloadItems = chosen.map((it) => ({
          alist_path: it.alist_path,
          filename: it.filename,
          file_size: it.file_size,
          media_type: it.matched_work.media_type,
          tmdb_id: it.matched_work.tmdb_id,
          title_hint: it.matched_work.title,
          season_number: it.season_number,
          episode_number: it.episode_number,
          version_label: it.version_label,
          recognition_trace: {
            raw_name: it.raw_name,
            cleaned_name: it.cleaned_name,
            inferred_title: it.inferred_title,
            source: it.source,
            reasoning: it.reasoning,
          },
        }));

        confirmImportBtn.disabled = true;
        const { ok, data } = await apiJson("/api/import/confirm", {
          method: "POST",
          body: { items: payloadItems },
        });
        confirmImportBtn.disabled = false;

        if (!ok || !data.task_id) {
          showToast(data.message || "创建入库任务失败", "error");
          return;
        }

        window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" });
        pollTaskUntilDone(data.task_id, (task) => {
          showToast(task.summary || "影视资料刮削与入库完成", "ok");
          if (taskActions) taskActions.classList.remove("hidden");
          loadDirectory(currentDir);
        });
      });
    }

    loadDirectory("/");
  }

  /* ---------- 8. 后台管理页交互 ---------- */
  function initAdminPage() {
    const root = document.getElementById("admin-page-root");
    if (!root) return;

    // 删除作品
    root.querySelectorAll("[data-admin-delete-work]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const wid = btn.getAttribute("data-admin-delete-work");
        const title = btn.getAttribute("data-work-title") || "该作品";
        if (!window.confirm(`确定要从本地媒体库移除《${title}》吗？（不会删除网盘源文件）`)) return;
        const { ok, data } = await apiJson(`/api/admin/works/${wid}`, { method: "DELETE" });
        if (!ok) {
          showToast(data.message || "删除失败", "error");
          return;
        }
        showToast(data.message || "已删除作品", "ok");
        window.location.href = "/admin";
      });
    });

    const editor = document.getElementById("admin-work-editor");
    if (!editor) return;
    const workId = editor.getAttribute("data-work-id");

    // 保存自定义显示标题
    const saveTitleBtn = document.getElementById("btn-admin-save-title");
    if (saveTitleBtn) {
      saveTitleBtn.addEventListener("click", async () => {
        const titleInput = document.getElementById("admin-custom-title");
        const custom_title = titleInput ? titleInput.value.trim() : "";
        const { ok, data } = await apiJson(`/api/admin/works/${workId}/title`, {
          method: "POST",
          body: { custom_title },
        });
        if (!ok) {
          showToast(data.message || "保存标题失败", "error");
          return;
        }
        showToast("显示标题已更新", "ok");
        setTimeout(() => window.location.reload(), 350);
      });
    }

    // 重新获取资料与评分
    const refreshWorkBtn = document.getElementById("btn-admin-refresh-work");
    if (refreshWorkBtn) {
      refreshWorkBtn.addEventListener("click", async () => {
        refreshWorkBtn.disabled = true;
        const orig = refreshWorkBtn.textContent;
        refreshWorkBtn.textContent = "正在从 TMDB / MDBList 刷新...";
        const { ok, data } = await apiJson(`/api/admin/works/${workId}/refresh`, {
          method: "POST",
          body: {},
        });
        refreshWorkBtn.disabled = false;
        refreshWorkBtn.textContent = orig;
        if (!ok) {
          showToast(data.message || "刷新资料失败", "error");
          return;
        }
        showToast(data.message || "资料已刷新", "ok");
        setTimeout(() => window.location.reload(), 400);
      });
    }

    // 更换候选 Logo / 海报 / 背景图
    let cachedCandidates = null;
    let activeCandKind = "logos";
    const candModal = document.getElementById("modal-candidate-images");
    const candGrid = document.getElementById("candidate-images-grid");

    function renderCandidateGrid() {
      if (!candGrid || !cachedCandidates) return;
      const list = cachedCandidates[activeCandKind] || [];
      const singularKind = { logos: "logo", posters: "poster", backdrops: "backdrop" }[activeCandKind];

      if (!list.length) {
        candGrid.innerHTML = `<div class="p-10 text-center text-xs" style="color: var(--text-muted);">TMDB 暂无该类别的候选图片</div>`;
        return;
      }

      const gridCols =
        activeCandKind === "posters"
          ? "grid-cols-2 sm:grid-cols-4 md:grid-cols-5"
          : activeCandKind === "logos"
          ? "grid-cols-2 sm:grid-cols-3"
          : "grid-cols-1 sm:grid-cols-2 md:grid-cols-3";

      candGrid.innerHTML = `
        <div class="grid ${gridCols} gap-3">
          ${list
            .map(
              (it) => `
            <button
              type="button"
              data-select-cand-kind="${singularKind}"
              data-select-cand-path="${escapeHtml(it.file_path)}"
              class="p-2.5 rounded-xl border text-left space-y-2 cursor-pointer transition hover:opacity-95"
              style="background: var(--bg-subtle); border-color: ${
                it.selected ? "var(--accent)" : "var(--border-subtle)"
              };"
            >
              <div class="${
                activeCandKind === "logos"
                  ? "logo-preview-well h-24 p-3"
                  : activeCandKind === "posters"
                  ? "aspect-[2/3] rounded-lg overflow-hidden"
                  : "aspect-video rounded-lg overflow-hidden"
              } flex items-center justify-center" style="${
                activeCandKind !== "logos" ? "background: var(--bg-elevated);" : ""
              }">
                <img src="${escapeHtml(mediaImgUrl(it.preview_path))}" alt="" class="${
                activeCandKind === "logos" ? "max-h-16 max-w-full object-contain" : "w-full h-full object-cover"
              }" />
              </div>
              <div class="flex items-center justify-between text-[11px]" style="color: var(--text-secondary);">
                <span>${escapeHtml(it.lang)} · ${it.width}×${it.height}</span>
                ${it.selected ? `<span class="font-bold" style="color: var(--text-primary);">当前使用</span>` : ""}
              </div>
            </button>
          `
            )
            .join("")}
        </div>
      `;
    }

    document.querySelectorAll("[data-open-image-picker]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        activeCandKind = btn.getAttribute("data-open-image-picker") || "logos";
        if (candModal) candModal.classList.remove("hidden");
        document.querySelectorAll("[data-cand-tab]").forEach((t) => {
          t.className = `${
            t.getAttribute("data-cand-tab") === activeCandKind ? "btn-primary" : "btn-secondary"
          } !py-1 !px-3.5 text-xs`;
        });

        if (!cachedCandidates) {
          candGrid.innerHTML = `<div class="p-10 text-center text-xs" style="color: var(--text-muted);">正在从 TMDB 拉取候选图片并缓存至本地...</div>`;
          const { ok, data } = await apiJson(`/api/admin/works/${workId}/images`);
          if (!ok || !data.images) {
            candGrid.innerHTML = `<div class="p-10 text-center text-xs" style="color: var(--status-err-fg);">${escapeHtml(
              data.message || "获取候选图片失败"
            )}</div>`;
            return;
          }
          cachedCandidates = data.images;
        }
        renderCandidateGrid();
      });
    });

    document.querySelectorAll("[data-cand-tab]").forEach((tab) => {
      tab.addEventListener("click", () => {
        activeCandKind = tab.getAttribute("data-cand-tab") || "logos";
        document.querySelectorAll("[data-cand-tab]").forEach((t) => {
          t.className = `${t === tab ? "btn-primary" : "btn-secondary"} !py-1 !px-3.5 text-xs`;
        });
        renderCandidateGrid();
      });
    });

    if (candGrid) {
      candGrid.addEventListener("click", async (e) => {
        const card = e.target.closest("[data-select-cand-path]");
        if (!card) return;
        const kind = card.getAttribute("data-select-cand-kind");
        const file_path = card.getAttribute("data-select-cand-path");
        showToast("正在下载高清原图至本地缓存...", "info");
        const { ok, data } = await apiJson(`/api/admin/works/${workId}/select-image`, {
          method: "POST",
          body: { kind, file_path },
        });
        if (!ok) {
          showToast(data.message || "更换图片失败", "error");
          return;
        }
        showToast(data.message || "图片已更换", "ok");
        setTimeout(() => window.location.reload(), 350);
      });
    }

    const clearLogoBtn = document.getElementById("btn-clear-logo");
    if (clearLogoBtn) {
      clearLogoBtn.addEventListener("click", async () => {
        const { ok, data } = await apiJson(`/api/admin/works/${workId}/select-image`, {
          method: "POST",
          body: { kind: "logo", file_path: "" },
        });
        if (ok) {
          showToast("已清空片名 Logo，改用文字标题显示", "ok");
          setTimeout(() => window.location.reload(), 350);
        } else {
          showToast(data.message || "操作失败", "error");
        }
      });
    }

    // 重新匹配到另一部 TMDB 作品
    const rematchSearchBtn = document.getElementById("btn-admin-rematch-search");
    const rematchResults = document.getElementById("admin-rematch-results");
    if (rematchSearchBtn && rematchResults) {
      rematchSearchBtn.addEventListener("click", async () => {
        const q = (document.getElementById("admin-rematch-query") || {}).value || "";
        const tp = (document.getElementById("admin-rematch-type") || {}).value || "";
        if (!q.trim()) {
          showToast("请输入要检索的新作品名称", "warn");
          return;
        }
        rematchResults.classList.remove("hidden");
        rematchResults.innerHTML = `<div class="p-4 text-xs" style="color: var(--text-muted);">正在检索 TMDB 候选条目...</div>`;
        const { ok, data } = await apiJson(
          `/api/import/tmdb-search?q=${encodeURIComponent(q.trim())}&type=${encodeURIComponent(tp)}`
        );
        if (!ok) {
          rematchResults.innerHTML = `<div class="p-4 text-xs" style="color: var(--status-err-fg);">${escapeHtml(
            data.message || "检索失败"
          )}</div>`;
          return;
        }
        const items = data.items || [];
        if (!items.length) {
          rematchResults.innerHTML = `<div class="p-4 text-xs" style="color: var(--text-muted);">未找到匹配的候选作品</div>`;
          return;
        }
        rematchResults.innerHTML = items
          .slice(0, 6)
          .map(
            (it) => `
            <div class="p-3 rounded-xl border flex items-center justify-between gap-3" style="border-color: var(--border-subtle); background: var(--bg-subtle);">
              <div class="flex items-center gap-3 min-w-0">
                <div class="w-9 h-12 rounded overflow-hidden shrink-0" style="background: var(--bg-elevated);">
                  ${
                    it.poster_local
                      ? `<img src="${escapeHtml(mediaImgUrl(it.poster_local))}" alt="" class="w-full h-full object-cover" />`
                      : ""
                  }
                </div>
                <div class="min-w-0">
                  <div class="text-xs sm:text-sm font-bold truncate">${escapeHtml(it.title)} ${
              it.year ? `(${it.year})` : ""
            }</div>
                  <div class="text-[11px]" style="color: var(--text-muted);">${
                    it.media_type === "tv" ? "剧集" : "电影"
                  } · TMDB #${it.tmdb_id} · ★ ${it.tmdb_rating || 0}</div>
                </div>
              </div>
              <button
                type="button"
                data-confirm-rematch-id="${it.tmdb_id}"
                data-confirm-rematch-type="${it.media_type}"
                data-confirm-rematch-title="${escapeHtml(it.title)}"
                class="btn-primary !py-1 !px-3 text-xs shrink-0"
              >
                匹配为此作品
              </button>
            </div>
          `
          )
          .join("");
      });

      rematchResults.addEventListener("click", async (e) => {
        const btn = e.target.closest("[data-confirm-rematch-id]");
        if (!btn) return;
        const newId = Number(btn.getAttribute("data-confirm-rematch-id"));
        const newType = btn.getAttribute("data-confirm-rematch-type");
        const newTitle = btn.getAttribute("data-confirm-rematch-title");
        btn.disabled = true;
        btn.textContent = "正在重匹配...";
        const { ok, data } = await apiJson(`/api/admin/works/${workId}/rematch`, {
          method: "POST",
          body: { media_type: newType, tmdb_id: newId },
        });
        btn.disabled = false;
        if (!ok) {
          btn.textContent = "匹配为此作品";
          showToast(data.message || "重新匹配失败", "error");
          return;
        }
        showToast(`已成功重新匹配为《${newTitle}》`, "ok");
        setTimeout(() => window.location.reload(), 400);
      });
    }

    // 文件与季集映射 / 电影多版本保存 / 移除文件
    const filesList = document.getElementById("admin-files-list");
    if (filesList) {
      filesList.addEventListener("click", async (e) => {
        const mapBtn = e.target.closest("[data-admin-save-map]");
        if (mapBtn) {
          const fid = mapBtn.getAttribute("data-admin-save-map");
          const sIn = document.querySelector(`[data-admin-map-season="${fid}"]`);
          const eIn = document.querySelector(`[data-admin-map-episode="${fid}"]`);
          const season_number = sIn && sIn.value !== "" ? Number(sIn.value) : null;
          const episode_number = eIn && eIn.value !== "" ? Number(eIn.value) : null;
          const { ok, data } = await apiJson(`/api/admin/works/${workId}/map-episode`, {
            method: "POST",
            body: { file_id: Number(fid), season_number, episode_number },
          });
          if (!ok) {
            showToast(data.message || "保存季集对应失败", "error");
            return;
          }
          showToast("文件与季集对应关系已更新", "ok");
          setTimeout(() => window.location.reload(), 350);
          return;
        }

        const verBtn = e.target.closest("[data-admin-save-version]");
        if (verBtn) {
          const fid = verBtn.getAttribute("data-admin-save-version");
          const vIn = document.querySelector(`[data-admin-version-input="${fid}"]`);
          const version_label = vIn ? vIn.value.trim() : "标准版";
          const { ok, data } = await apiJson(`/api/admin/works/${workId}/file-version`, {
            method: "POST",
            body: { file_id: Number(fid), version_label },
          });
          if (!ok) {
            showToast(data.message || "保存版本标签失败", "error");
            return;
          }
          showToast("电影版本名称已保存", "ok");
          return;
        }

        const rmBtn = e.target.closest("[data-admin-remove-file]");
        if (rmBtn) {
          const fid = rmBtn.getAttribute("data-admin-remove-file");
          if (!window.confirm("确定解除此网盘文件与当前作品的关联吗？")) return;
          const { ok, data } = await apiJson(`/api/admin/works/${workId}/files/${fid}`, { method: "DELETE" });
          if (!ok) {
            showToast(data.message || "移除文件失败", "error");
            return;
          }
          showToast("已移除关联文件", "ok");
          setTimeout(() => window.location.reload(), 350);
        }
      });
    }

    // 关联额外网盘文件模态框
    const openAttachBtn = document.getElementById("btn-open-attach-file");
    const attachModal = document.getElementById("modal-attach-file");
    const attachList = document.getElementById("attach-alist-list");
    const attachBc = document.getElementById("attach-alist-breadcrumbs");
    const attachPathInput = document.getElementById("attach-file-path");
    const confirmAttachBtn = document.getElementById("btn-confirm-attach-file");

    async function loadAttachDir(path) {
      if (!attachList) return;
      attachList.innerHTML = `<div class="p-4 text-xs text-center" style="color: var(--text-muted);">读取中...</div>`;
      const { ok, data } = await apiJson(`/api/import/browse?path=${encodeURIComponent(path || "/")}`);
      if (!ok || !data.data) {
        attachList.innerHTML = `<div class="p-4 text-xs text-center" style="color: var(--status-err-fg);">读取目录失败</div>`;
        return;
      }
      const d = data.data;
      if (attachBc) {
        attachBc.innerHTML = (d.breadcrumbs || [])
          .map(
            (b) =>
              `<button type="button" data-attach-bc="${escapeHtml(
                b.path
              )}" class="btn-ghost !py-0.5 !px-2 text-xs">${escapeHtml(b.name)}</button>`
          )
          .join(" / ");
      }
      attachList.innerHTML = (d.entries || [])
        .filter((it) => it.is_dir || it.is_video)
        .map((it) =>
          it.is_dir
            ? `<button type="button" data-attach-dir="${escapeHtml(
                it.path
              )}" class="w-full text-left px-3 py-2 text-xs font-semibold hover:opacity-80 bg-transparent border-0 cursor-pointer flex justify-between" style="color: var(--text-primary);"><span>📁 ${escapeHtml(
                it.name
              )}</span><span style="color: var(--text-muted);">进入</span></button>`
            : `<button type="button" data-attach-pick="${escapeHtml(
                it.path
              )}" class="w-full text-left px-3 py-2 text-xs hover:opacity-80 bg-transparent border-0 cursor-pointer flex justify-between" style="color: var(--text-primary);"><span class="truncate">🎬 ${escapeHtml(
                it.name
              )}</span><span class="shrink-0 ml-2" style="color: var(--text-muted);">${escapeHtml(
                it.size_human
              )}</span></button>`
        )
        .join("");
    }

    if (openAttachBtn && attachModal) {
      openAttachBtn.addEventListener("click", () => {
        attachModal.classList.remove("hidden");
        loadAttachDir("/");
      });
    }
    if (attachBc) {
      attachBc.addEventListener("click", (e) => {
        const b = e.target.closest("[data-attach-bc]");
        if (b) loadAttachDir(b.getAttribute("data-attach-bc"));
      });
    }
    if (attachList) {
      attachList.addEventListener("click", (e) => {
        const d = e.target.closest("[data-attach-dir]");
        if (d) {
          loadAttachDir(d.getAttribute("data-attach-dir"));
          return;
        }
        const p = e.target.closest("[data-attach-pick]");
        if (p && attachPathInput) {
          attachPathInput.value = p.getAttribute("data-attach-pick");
        }
      });
    }
    if (confirmAttachBtn) {
      confirmAttachBtn.addEventListener("click", async () => {
        const alist_path = attachPathInput ? attachPathInput.value.trim() : "";
        if (!alist_path) {
          showToast("请先选择或填写要关联的网盘视频文件路径", "warn");
          return;
        }
        const verEl = document.getElementById("attach-version-label");
        const sEl = document.getElementById("attach-season-no");
        const eEl = document.getElementById("attach-episode-no");

        const { ok, data } = await apiJson(`/api/admin/works/${workId}/attach-file`, {
          method: "POST",
          body: {
            alist_path,
            version_label: verEl ? verEl.value.trim() : "",
            season_number: sEl ? Number(sEl.value) : null,
            episode_number: eEl ? Number(eEl.value) : null,
          },
        });
        if (!ok) {
          showToast(data.message || "关联文件失败", "error");
          return;
        }
        showToast("已成功关联新网盘文件", "ok");
        setTimeout(() => window.location.reload(), 350);
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    initThemeToggle();
    initMobileNavAndModals();
    initHeroAndRails();
    initPlaybackAndProgress();
    initSetupAndSettings();
    initImportPage();
    initAdminPage();
  });
})();
