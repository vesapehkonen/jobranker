const reportConfig = JSON.parse(
    document.getElementById("report-config").textContent
);
const API_TOKEN = reportConfig.apiToken;

let reportLoadedVersion = reportConfig.reportVersion;
let reportCheckTimer = null;
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

function authHeaders() {
    return { "Authorization": `Bearer ${API_TOKEN}` };
}

function processingBadge(job) {
    const status = job.processing_status || "";
    if (!status) return '<span class="muted">—</span>';
    const css = status === "failed" ? "failed" :
        status === "processing" ? "active" :
        status === "done" ? "done" : "pending";
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

function renderJobs(data) {
    const body = document.getElementById("jobs-body");
    body.innerHTML = "";
    data.items.forEach(job => {
        const uid = escapeHtml(job.job_uid);
        const row = document.createElement("tr");
        row.className = "job-row";
        row.dataset.status = job.status;
        row.innerHTML = `
            <td><div class="score">${job.score ?? "—"}</div>
                <div class="recommendation">${escapeHtml(job.recommendation || "")}</div></td>
            <td>${job.recommended_profile
                ? `<span class="resume-pill">${escapeHtml(job.recommended_profile)}</span>`
                : '<span class="muted">—</span>'}</td>
            <td><div class="status-cell">
                <span class="status status-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
                <span class="local-time" data-time="${escapeHtml(job.status_updated_at || "")}"></span>
            </div></td>
            <td><div class="job-main">
                <div class="company">${escapeHtml(job.company || "Unknown company")}</div>
                <a class="job-title" href="${escapeHtml(job.url || "#")}" target="_blank">${escapeHtml(job.title || "Untitled job")}</a>
                <div class="job-summary">${escapeHtml(job.short_summary || "")}</div>
                <div class="muted">${escapeHtml(job.job_source || "")}${job.external_job_id ? ` · Job ID: ${escapeHtml(job.external_job_id)}` : ""}</div>
            </div></td>
            <td>${escapeHtml(job.main_skill || "")}</td>
            <td>${escapeHtml(job.location || "")}</td>
            <td>${processingBadge(job)}</td>
            <td><div class="actions">
                <button type="button" onclick="toggleDetails('${uid}')">Details</button>
                ${job.processing_status === "failed" ? `<button type="button" onclick="retryJob('${uid}')">Retry</button>` : ""}
                <select onchange="changeStatus('${uid}', this)">${statusOptions(job.status)}</select>
            </div></td>`;
        body.appendChild(row);
        const details = document.createElement("tr");
        details.id = `details-${job.job_uid}`;
        details.className = "details-row";
        details.innerHTML = '<td colspan="8"><div class="details-card"><span class="muted">Loading details…</span></div></td>';
        body.appendChild(details);
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
    const params = new URLSearchParams({
        search: jobState.search, status: jobState.status, sort: jobState.sort,
        page: jobState.page, page_size: jobState.pageSize,
    });
    if (jobState.minimumScore) params.set("minimum_score", jobState.minimumScore);
    const response = await fetch(`/jobs?${params}`, { headers: authHeaders() });
    if (!response.ok) {
        document.getElementById("results-summary").textContent = `Could not load jobs: HTTP ${response.status}`;
        return;
    }
    renderJobs(await response.json());
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

async function toggleDetails(jobUid) {
    const row = document.getElementById(`details-${jobUid}`);
    if (!row) return;
    if (row.style.display === "table-row") {
        row.style.display = "none";
        return;
    }
    row.style.display = "table-row";
    if (row.dataset.loaded) return;
    const response = await fetch(`/jobs/${jobUid}`, { headers: authHeaders() });
    if (!response.ok) {
        row.querySelector(".details-card").textContent = `Could not load details: HTTP ${response.status}`;
        return;
    }
    const job = await response.json();
    const profileScores = Object.entries(job.profile_scores || {})
        .map(([name, score]) => `<li><strong>${escapeHtml(name)}</strong>: ${score}</li>`).join("");
    row.querySelector("td").innerHTML = `<div class="details-card">
        <div class="details-top"><div>
            <div class="details-title">${escapeHtml(job.company || "Unknown company")} — ${escapeHtml(job.title || "Untitled job")}</div>
            <div class="details-subtitle">Internal UID: ${escapeHtml(job.job_uid)}${job.external_job_id ? ` · Job ID: ${escapeHtml(job.external_job_id)}` : ""}</div>
        </div><div><div class="muted">Resume match scores</div>
            ${profileScores ? `<ul class="profile-score-list">${profileScores}</ul>` : '<div class="muted">No profile scores</div>'}
        </div></div>
        <div class="details-grid">
            ${job.processing_error ? `<section class="detail-section full"><h3>Processing Error</h3><pre class="error-box">${escapeHtml(job.processing_error)}</pre></section>` : ""}
            <section class="detail-section"><h3>Matched strengths</h3>${listHtml(job.matched_strengths)}</section>
            <section class="detail-section"><h3>Weak areas</h3>${listHtml(job.weak_areas)}</section>
            <section class="detail-section"><h3>Interview risk</h3>${listHtml(job.interview_risk)}</section>
            <section class="detail-section"><h3>Requirements</h3>${listHtml(job.requirements)}</section>
            <section class="detail-section"><h3>Preferred requirements</h3>${listHtml(job.preferred_requirements)}</section>
            <section class="detail-section"><h3>Technologies</h3>${listHtml(job.technologies)}</section>
            <section class="detail-section"><h3>Benefits</h3>${listHtml(job.benefits)}</section>
            <section class="detail-section"><h3>Job info</h3><div class="info-grid">
                <div class="info-label">Source</div><div>${escapeHtml(job.job_source || "")}</div>
                <div class="info-label">Job ID</div><div>${escapeHtml(job.external_job_id || "")}</div>
                <div class="info-label">Workplace</div><div>${escapeHtml(job.workplace_type || "")}</div>
                <div class="info-label">Employment</div><div>${escapeHtml(job.employment_type || "")}</div>
                <div class="info-label">Education</div><div>${escapeHtml(job.education_requirement || "")}</div>
                <div class="info-label">Salary</div><div>${escapeHtml(job.salary_range || "")}</div>
                <div class="info-label">Created</div><div class="local-time" data-time="${escapeHtml(job.created_at_raw || "")}"></div>
            </div></section>
            <section class="detail-section full"><h3>Reasoning</h3><p>${escapeHtml(job.reasoning || "No ranking reasoning available.")}</p></section>
            <section class="detail-section full"><h3>Summary</h3><p>${escapeHtml(job.summary || job.short_summary || "No summary available.")}</p></section>
            ${job.description ? `<section class="detail-section full"><h3>Description</h3><p>${escapeHtml(job.description)}</p></section>` : ""}
        </div></div>`;
    row.dataset.loaded = "true";
    formatLocalTimes();
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
            reportLoadedVersion = data.version;
            loadJobs();
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
