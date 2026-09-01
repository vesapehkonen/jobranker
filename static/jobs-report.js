const reportConfig = JSON.parse(
    document.getElementById("report-config").textContent
);
const API_TOKEN = reportConfig.apiToken;

let reportLoadedVersion = reportConfig.reportVersion;
let reportCheckTimer = null;
let selectedJobUid = null;
let detailRequestId = 0;
let drawerTrigger = null;
let jobsRequestId = 0;
const savedStatus = localStorage.getItem("jobReportFilter");
const jobState = {
    search: localStorage.getItem("jobReportSearch") || "",
    status: !savedStatus || savedStatus === "active" ? "new" : savedStatus,
    sort: localStorage.getItem("jobReportSort") || "newest",
    minimumScore: localStorage.getItem("jobReportMinimumScore") || "",
    pageSize: Number(localStorage.getItem("jobReportPageSize") || 25),
    page: 1,
    totalPages: 0,
};
let searchTimer = null;

function escapeHtml(value) {
    const element = document.createElement("div");
    element.textContent = value == null ? "" : String(value);
    return element.innerHTML;
}

function compactText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
}

function safeExternalUrl(value) {
    try {
        const url = new URL(value);
        return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch {
        return "";
    }
}

function recommendationLabel(score) {
    const numericScore = Number(score);
    if (score == null || score === "" || !Number.isFinite(numericScore)) return "";
    if (numericScore >= 88) return "strong";
    if (numericScore >= 70) return "good";
    if (numericScore >= 50) return "weak";
    return "no match";
}

function scoreHtml(score) {
    if (score == null || score === "") {
        return `
            <div class="score">—</div>
            <div class="score-bar" aria-hidden="true"></div>
        `;
    }
    const numericScore = Number(score);
    if (!Number.isFinite(numericScore)) {
        return `
            <div class="score">—</div>
            <div class="score-bar" aria-hidden="true"></div>
        `;
    }
    const boundedScore = Math.max(0, Math.min(100, numericScore));
    const scoreClass = boundedScore >= 88 ? "strong" :
        boundedScore >= 70 ? "good" :
        boundedScore >= 50 ? "fair" : "low";
    return `
        <div class="score">${escapeHtml(numericScore)}</div>
        <div class="score-bar" role="img" aria-label="Fit score ${escapeHtml(numericScore)} out of 100">
            <span class="score-bar-fill score-bar-${scoreClass}" style="width: ${boundedScore}%"></span>
        </div>
    `;
}

function authHeaders() {
    return { "Authorization": `Bearer ${API_TOKEN}` };
}

function processingBadge(job) {
    const status = job.processing_status || "";
    if (!status || status === "done") return "";
    const css = status === "failed" ? "failed" :
        status === "processing" ? "active" :
        "pending";
    const text = status === "processing" ? (job.processing_phase || status) : status;
    return `<span class="processing processing-${css}">${escapeHtml(text)}</span>`;
}

function statusOptions(current) {
    const options = [
        ["new", "New"], ["interested", "Interested"], ["applied", "Applied"],
        ["recruiter_contact", "Recruiter"], ["interview", "Interview"],
        ["final_round", "Final round"], ["offer", "Offer"], ["skipped", "Skipped"],
        ["rejected", "Rejected"], ["withdrawn", "Withdrawn"], ["archived", "Archived"],
    ];
    return options.map(([value, label]) =>
        `<option value="${value}" ${value === current ? "selected" : ""}>${label}</option>`
    ).join("");
}

function renderJobsLoading() {
    const body = document.getElementById("jobs-body");
    body.setAttribute("aria-busy", "true");
    body.innerHTML = Array.from({ length: 5 }, (_, index) => `
        <tr class="skeleton-row" aria-hidden="true">
            <td><div class="skeleton-line ${index % 2 ? "short" : ""}"></div></td>
            <td><div class="skeleton-line medium"></div></td>
            <td><div class="skeleton-line"></div></td>
            <td><div class="skeleton-line medium"></div></td>
            <td><div class="skeleton-line short"></div></td>
            <td><div class="skeleton-line medium"></div></td>
        </tr>
    `).join("");
    document.getElementById("results-summary").textContent = "Loading jobs…";
    document.getElementById("page-summary").textContent = "";
    document.getElementById("previous-page").disabled = true;
    document.getElementById("next-page").disabled = true;
}

function renderTableState(title, message, retry = false) {
    const body = document.getElementById("jobs-body");
    body.setAttribute("aria-busy", "false");
    body.innerHTML = `
        <tr class="state-row">
            <td colspan="6">
                <div class="table-state">
                    <h2 class="table-state-title">${escapeHtml(title)}</h2>
                    <p class="table-state-message">${escapeHtml(message)}</p>
                    ${retry ? '<button type="button" onclick="loadJobs()">Try again</button>' : ""}
                </div>
            </td>
        </tr>
    `;
    document.getElementById("page-summary").textContent = "";
    document.getElementById("previous-page").disabled = true;
    document.getElementById("next-page").disabled = true;
}

function emptyStateCopy() {
    if (jobState.search || jobState.minimumScore) {
        return [
            "No jobs match these filters",
            "Try changing the search text, lowering the minimum score, or selecting another status.",
        ];
    }
    if (jobState.status === "new") {
        return [
            "No new jobs to review",
            "Newly captured jobs will appear here after they enter the processing queue.",
        ];
    }
    return [
        "No jobs in this status",
        "Choose another status or select All to review every captured job.",
    ];
}

function renderJobs(data) {
    const body = document.getElementById("jobs-body");
    body.innerHTML = "";
    body.setAttribute("aria-busy", "false");
    if (!data.items.length) {
        const [title, message] = emptyStateCopy();
        renderTableState(title, message);
    }
    data.items.forEach(job => {
        const uid = escapeHtml(job.job_uid);
        const location = compactText(job.location) || "Location unavailable";
        const workArrangement = compactText(
            [job.workplace_type, job.employment_type].filter(Boolean).join(" · ")
        ) || "Work arrangement unavailable";
        const salary = compactText(job.salary_range) || "Salary unavailable";
        const row = document.createElement("tr");
        row.className = "job-row";
        row.dataset.status = job.status;
        row.innerHTML = `
            <td><div class="score-cell">${scoreHtml(job.score)}
                <div class="recommendation">${escapeHtml(recommendationLabel(job.score))}</div>
                ${job.recommended_profile
                    ? `<span class="resume-pill">${escapeHtml(job.recommended_profile)}</span>`
                    : ""}
            </div></td>
            <td><div class="status-cell">
                <span class="status status-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
                <span class="local-time" data-time="${escapeHtml(job.status_updated_at || "")}"></span>
            </div></td>
            <td><div class="job-main">
                <div class="company">${escapeHtml(job.company || "Unknown company")}</div>
                <a class="job-title" href="${escapeHtml(job.url || "#")}" target="_blank">${escapeHtml(job.title || "Untitled job")}</a>
                <div class="job-summary">${escapeHtml(job.short_summary || "")}</div>
                <div class="muted">${escapeHtml(job.job_source || "")}${job.external_job_id ? ` · Job ID: ${escapeHtml(job.external_job_id)}` : ""}</div>
                ${processingBadge(job)}
            </div></td>
            <td><div class="practical-details">
                <strong class="practical-location" title="${escapeHtml(location)}">${escapeHtml(location)}</strong>
                <span class="practical-meta" title="${escapeHtml(workArrangement)}">${escapeHtml(workArrangement)}</span>
                <span class="practical-salary" title="${escapeHtml(salary)}">${escapeHtml(salary)}</span>
            </div></td>
            <td>${escapeHtml(job.main_skill || "")}</td>
            <td><div class="actions">
                <button id="details-button-${uid}" type="button" onclick="openJobDetails('${uid}', this)">Details</button>
                ${job.processing_status === "failed" ? `<button type="button" onclick="retryJob('${uid}')">Retry</button>` : ""}
                <select onchange="changeStatus('${uid}', this)">${statusOptions(job.status)}</select>
            </div></td>`;
        body.appendChild(row);
    });
    formatLocalTimes();
    document.getElementById("results-summary").textContent =
        data.total_items ? `Showing ${(data.page - 1) * data.page_size + 1}–${Math.min(data.page * data.page_size, data.total_items)} of ${data.total_items} jobs` : "No matching jobs";
    document.getElementById("page-summary").textContent =
        `Page ${data.total_pages ? data.page : 0} of ${data.total_pages}`;
    document.getElementById("previous-page").disabled = data.page <= 1;
    document.getElementById("next-page").disabled = data.page >= data.total_pages;
    jobState.totalPages = data.total_pages;
}

async function loadJobs() {
    const requestId = ++jobsRequestId;
    renderJobsLoading();
    const params = new URLSearchParams({
        search: jobState.search, status: jobState.status, sort: jobState.sort,
        page: jobState.page, page_size: jobState.pageSize,
    });
    if (jobState.minimumScore) params.set("minimum_score", jobState.minimumScore);
    let response;
    try {
        response = await fetch(`/jobs?${params}`, { headers: authHeaders() });
    } catch (error) {
        if (requestId !== jobsRequestId) return;
        renderTableState(
            "Could not load jobs",
            "The JobRanker API could not be reached. Check that the application is running.",
            true,
        );
        document.getElementById("results-summary").textContent = "Could not load jobs";
        console.error("Job list request failed", error);
        return;
    }
    if (requestId !== jobsRequestId) return;
    if (!response.ok) {
        renderTableState(
            "Could not load jobs",
            `The API returned HTTP ${response.status}.`,
            true,
        );
        document.getElementById("results-summary").textContent =
            `Could not load jobs: HTTP ${response.status}`;
        return;
    }
    const data = await response.json();
    if (requestId !== jobsRequestId) return;
    renderJobs(data);
}

async function changeStatus(jobUid, selectElement) {
    const status = selectElement.value;

    const response = await fetch(`/jobs/${jobUid}/status`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${API_TOKEN}`,
        },
        body: JSON.stringify({ status: status }),
    });

    if (!response.ok) {
        const text = await response.text();
        alert(`Failed to update job status: HTTP ${response.status}\n${text}`);
        return;
    }

    loadJobs();
}

async function retryJob(jobUid) {
    const response = await fetch(`/jobs/${jobUid}/retry`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${API_TOKEN}`,
        },
    });

    if (!response.ok) {
        const text = await response.text();
        alert(`Failed to retry job: HTTP ${response.status}\n${text}`);
        return;
    }

    loadJobs();
}

function listHtml(items) {
    return items && items.length
        ? `<ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
        : '<p class="muted">None listed</p>';
}

function dimensionScoresHtml(scores) {
    const dimensions = [
        ["technical_skill_fit", "Technical"],
        ["role_experience_fit", "Experience"],
        ["domain_fit", "Domain"],
        ["seniority_fit", "Seniority"],
        ["resume_evidence_strength", "Evidence"],
    ];
    return dimensions.map(([key, label]) => `
        <div class="dimension-score">
            <div class="dimension-score-label">${label}</div>
            <div class="dimension-score-value">${escapeHtml(scores?.[key] ?? "—")}</div>
        </div>
    `).join("");
}

async function openJobDetails(jobUid, trigger = null) {
    const drawer = document.getElementById("job-drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    const eyebrow = document.getElementById("drawer-eyebrow");
    const title = document.getElementById("drawer-title");
    const subtitle = document.getElementById("drawer-subtitle");
    const content = document.getElementById("drawer-content");
    selectedJobUid = jobUid;
    drawerTrigger = trigger ||
        document.getElementById(`details-button-${jobUid}`) ||
        drawerTrigger;
    const requestId = ++detailRequestId;

    drawer.hidden = false;
    backdrop.hidden = false;
    document.body.classList.add("drawer-open");
    eyebrow.textContent = "Job details";
    title.textContent = "Loading…";
    subtitle.textContent = "";
    content.innerHTML = `<div class="drawer-loading" aria-label="Loading job details">
        <div class="skeleton-line medium"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line short"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line medium"></div>
    </div>`;
    if (trigger) {
        document.getElementById("close-drawer").focus();
    }

    let response;
    try {
        response = await fetch(`/jobs/${jobUid}`, { headers: authHeaders() });
    } catch (error) {
        if (requestId !== detailRequestId) return;
        eyebrow.textContent = "Job details";
        title.textContent = "Could not load job";
        content.textContent = "Could not connect to the JobRanker API.";
        console.error("Job detail request failed", error);
        return;
    }
    if (requestId !== detailRequestId) return;
    if (!response.ok) {
        eyebrow.textContent = "Job details";
        title.textContent = "Could not load job";
        content.textContent = `Could not load details: HTTP ${response.status}`;
        return;
    }
    const job = await response.json();
    if (requestId !== detailRequestId) return;
    eyebrow.textContent = job.company || "Unknown company";
    title.textContent = job.title || "Untitled job";
    subtitle.textContent = [
        compactText(job.location),
        compactText(job.workplace_type),
        compactText(job.employment_type),
    ].filter(Boolean).join(" · ");
    const externalUrl = safeExternalUrl(job.url);
    const savedDescriptionUrl = `/jobs/${encodeURIComponent(job.job_uid)}/description`;
    const otherProfileScores = Object.entries(job.profile_scores || {})
        .filter(([name]) => name !== job.recommended_profile)
        .map(([name, score]) => `<li><strong>${escapeHtml(name)}</strong>: ${escapeHtml(score)}</li>`).join("");
    content.innerHTML = `<div class="details-card">
        <div class="drawer-overview">
            <div class="fit-overview">
                <div class="fit-overview-score">${escapeHtml(job.score ?? "—")}</div>
                <div>
                    <div class="fit-overview-label">${escapeHtml(recommendationLabel(job.score) || "Not ranked")}</div>
                    ${job.recommended_profile ? `<span class="resume-pill">${escapeHtml(job.recommended_profile)}</span>` : ""}
                </div>
            </div>
            <div class="posting-links">
                <a class="secondary-link" href="${escapeHtml(savedDescriptionUrl)}" target="_blank" rel="noopener noreferrer">Saved job description ↗</a>
                ${externalUrl ? `<a class="primary-link" href="${escapeHtml(externalUrl)}" target="_blank" rel="noopener noreferrer">Open job posting ↗</a>` : ""}
            </div>
        </div>
        <div class="details-grid">
            ${job.processing_error ? `<section class="detail-section full"><h3>Processing Error</h3><pre class="error-box">${escapeHtml(job.processing_error)}</pre></section>` : ""}
            <section class="detail-section full"><h3>Notes</h3>
                <div class="notes-editor">
                    <textarea aria-label="Notes for ${escapeHtml(job.title || "job")}">${escapeHtml(job.notes || "")}</textarea>
                    <div class="notes-actions">
                        <button type="button" onclick="saveNotes('${escapeHtml(job.job_uid)}', this)">Save notes</button>
                        <span class="notes-save-status" role="status"></span>
                    </div>
                </div>
            </section>
            <section class="detail-section full">
                <h3>Fit breakdown</h3>
                <div class="dimension-scores">${dimensionScoresHtml(job.dimension_scores || {})}</div>
            </section>
            ${otherProfileScores ? `<section class="detail-section full"><h3>Other resume scores</h3><ul class="profile-score-list">${otherProfileScores}</ul></section>` : ""}
            <section class="detail-section"><h3>Matched strengths</h3>${listHtml(job.matched_strengths)}</section>
            <section class="detail-section"><h3>Weak areas</h3>${listHtml(job.weak_areas)}</section>
            <section class="detail-section"><h3>Requirements</h3>${listHtml(job.requirements)}</section>
            <section class="detail-section"><h3>Preferred requirements</h3>${listHtml(job.preferred_requirements)}</section>
            <section class="detail-section"><h3>Interview risk</h3>${listHtml(job.interview_risk)}</section>
            <section class="detail-section"><h3>Technologies</h3>${listHtml(job.technologies)}</section>
            <section class="detail-section"><h3>Benefits</h3>${listHtml(job.benefits)}</section>
            <section class="detail-section"><h3>Job info</h3><div class="info-grid">
                <div class="info-label">Source</div><div>${escapeHtml(job.job_source || "")}</div>
                <div class="info-label">Job ID</div><div>${escapeHtml(job.external_job_id || "")}</div>
                <div class="info-label">Internal UID</div><div>${escapeHtml(job.job_uid)}</div>
                <div class="info-label">Workplace</div><div>${escapeHtml(job.workplace_type || "")}</div>
                <div class="info-label">Employment</div><div>${escapeHtml(job.employment_type || "")}</div>
                <div class="info-label">Education</div><div>${escapeHtml(job.education_requirement || "")}</div>
                <div class="info-label">Salary</div><div>${escapeHtml(job.salary_range || "")}</div>
                <div class="info-label">Created</div><div class="local-time" data-time="${escapeHtml(job.created_at_raw || "")}"></div>
            </div></section>
            <section class="detail-section full"><h3>Summary</h3><p>${escapeHtml(job.summary || job.short_summary || "No summary available.")}</p></section>
            <section class="detail-section full"><h3>Ranking reasoning</h3><p>${escapeHtml(job.reasoning || "No ranking reasoning available.")}</p></section>
            ${job.description ? `<section class="detail-section full"><h3>Description</h3><p>${escapeHtml(job.description)}</p></section>` : ""}
        </div></div>`;
    formatLocalTimes();
}

function closeJobDetails() {
    document.getElementById("job-drawer").hidden = true;
    document.getElementById("drawer-backdrop").hidden = true;
    document.body.classList.remove("drawer-open");
    selectedJobUid = null;
    detailRequestId += 1;
    if (drawerTrigger && document.contains(drawerTrigger)) {
        drawerTrigger.focus();
    }
    drawerTrigger = null;
}

async function saveNotes(jobUid, button) {
    const editor = button.closest(".notes-editor");
    const textarea = editor.querySelector("textarea");
    const status = editor.querySelector(".notes-save-status");
    button.disabled = true;
    status.textContent = "Saving…";

    try {
        const response = await fetch(`/jobs/${jobUid}/notes`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${API_TOKEN}`,
            },
            body: JSON.stringify({ notes: textarea.value }),
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`HTTP ${response.status}: ${text}`);
        }
        status.textContent = "Saved";
    } catch (error) {
        status.textContent = "Could not save notes";
        console.error("Notes update failed", error);
    } finally {
        button.disabled = false;
    }
}

function filterStatus(mode) {
    localStorage.setItem("jobReportFilter", mode);
    jobState.status = mode;
    jobState.page = 1;

    document.querySelectorAll(".filter-button").forEach(btn => {
        btn.classList.remove("active");

        if (btn.dataset.filter === mode) {
            btn.classList.add("active");
        }
    });
    loadJobs();
}

async function checkReportUpdate() {
    if (document.hidden) {
        return;
    }

  try {
        const response = await fetch("/report/status", {
            headers: {
                "Content-Type": "application/json",
            },
        });

        if (!response.ok) {
            return;
        }

        const data = await response.json();

        if (typeof data.total_jobs === "number") {
            document.getElementById("total-jobs").textContent = `Total jobs: ${data.total_jobs}`;
        }
        if (data.exists && data.version !== reportLoadedVersion) {
            const openJobUid = selectedJobUid;
            reportLoadedVersion = data.version;
            await loadJobs();
            if (openJobUid) {
                openJobDetails(openJobUid);
            }
        }
    } catch (error) {
        console.error("Report status check failed", error);
    }
}

function startReportChecking() {
    if (reportCheckTimer) {
        return;
    }

    reportCheckTimer = setInterval(checkReportUpdate, 5000);
}

function stopReportChecking() {
    if (!reportCheckTimer) {
        return;
    }

    clearInterval(reportCheckTimer);
    reportCheckTimer = null;
}

document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        stopReportChecking();
    } else {
        checkReportUpdate();
        startReportChecking();
    }
});

document.getElementById("job-search").value = jobState.search;
document.getElementById("sort-order").value = jobState.sort;
document.getElementById("score-filter").value = jobState.minimumScore;
document.getElementById("page-size").value = String(jobState.pageSize);
document.getElementById("job-search").addEventListener("input", event => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        jobState.search = event.target.value.trim();
        jobState.page = 1;
        localStorage.setItem("jobReportSearch", jobState.search);
        loadJobs();
    }, 250);
});
document.getElementById("sort-order").addEventListener("change", event => {
    jobState.sort = event.target.value;
    jobState.page = 1;
    localStorage.setItem("jobReportSort", jobState.sort);
    loadJobs();
});
document.getElementById("score-filter").addEventListener("change", event => {
    jobState.minimumScore = event.target.value;
    jobState.page = 1;
    localStorage.setItem("jobReportMinimumScore", jobState.minimumScore);
    loadJobs();
});
document.getElementById("page-size").addEventListener("change", event => {
    jobState.pageSize = Number(event.target.value);
    jobState.page = 1;
    localStorage.setItem("jobReportPageSize", jobState.pageSize);
    loadJobs();
});
document.getElementById("previous-page").addEventListener("click", () => {
    if (jobState.page > 1) {
        jobState.page -= 1;
        loadJobs();
    }
});
document.getElementById("next-page").addEventListener("click", () => {
    if (jobState.page < jobState.totalPages) {
        jobState.page += 1;
        loadJobs();
    }
});
document.getElementById("close-drawer").addEventListener("click", closeJobDetails);
document.getElementById("drawer-backdrop").addEventListener("click", closeJobDetails);
document.addEventListener("keydown", event => {
    if (event.key === "Escape" && selectedJobUid) {
        closeJobDetails();
    }
});

filterStatus(jobState.status);

if (!document.hidden) {
    startReportChecking();
}

function formatLocalTimes() {
    document.querySelectorAll(".local-time").forEach(element => {
        const raw = element.dataset.time;

        if (!raw) {
            element.textContent = "";
            return;
        }

        const date = new Date(raw);

        if (Number.isNaN(date.getTime())) {
            element.textContent = raw;
            return;
        }

        element.textContent = date.toLocaleString(undefined, {
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    });
}

formatLocalTimes();
