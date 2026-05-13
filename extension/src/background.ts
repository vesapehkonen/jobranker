const REPORT_URL = "http://127.0.0.1:8000/report";
const CAPTURE_URL = "http://127.0.0.1:8000/jobs/capture";

const TOKEN_STORAGE_KEY = "apiToken";

async function getApiToken(tabId: number): Promise<string | null> {
  const stored = await chrome.storage.local.get(TOKEN_STORAGE_KEY);
  let token = stored[TOKEN_STORAGE_KEY] as string | undefined;

  if (token) return token;

  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => window.prompt("Enter API token"),
  });

  token = result?.trim();

  if (!token) return null;

  await chrome.storage.local.set({
    [TOKEN_STORAGE_KEY]: token,
  });

  return token;
}

type ToastType = "loading" | "success" | "error" | "warning";

async function showOrUpdateToast(
  tabId: number,
  title: string,
  message: string,
  type: ToastType,
  showReportLink = false
) {
  await chrome.scripting.executeScript({
    target: { tabId },
    args: [title, message, type, REPORT_URL, showReportLink],
    func: (title, message, type, reportUrl, showReportLink) => {
      let toast = document.getElementById("job-capture-toast");

      if (!toast) {
        toast = document.createElement("div");
        toast.id = "job-capture-toast";

        Object.assign(toast.style, {
          position: "fixed",
          top: "20px",
          right: "20px",
          zIndex: "2147483647",
          color: "white",
          padding: "14px 16px",
          borderRadius: "10px",
          boxShadow: "0 10px 25px rgba(0,0,0,0.25)",
          fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
          fontSize: "14px",
          maxWidth: "340px",
          transition: "all 0.2s ease",
        });

        document.body.appendChild(toast);
      }

      let bg = "#2563eb";
      if (type === "success") bg = "#0f766e";
      if (type === "error") bg = "#b91c1c";
      if (type === "warning") bg = "#92400e";

      toast.style.background = bg;
      toast.innerHTML = `
        <div style="font-weight:700; margin-bottom:4px;">${title}</div>
        <div style="margin-bottom:${showReportLink ? "8px" : "0"};">${message}</div>
        ${
          showReportLink
            ? `<a href="${reportUrl}" target="_blank" style="color:white; text-decoration:underline;">Open report</a>`
            : ""
        }
      `;

      if (type !== "loading") {
        setTimeout(() => {
          toast?.remove();
        }, 7000);
      }
    },
  });
}

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id) return;

  await showOrUpdateToast(
    tab.id,
    "Capturing job",
    "Sending page to local AI pipeline...",
    "loading"
  );

  const token = await getApiToken(tab.id);
  if (!token) {
    await showOrUpdateToast(
      tab.id,
      "Token missing",
      "API token was not set.",
      "error"
    );
    return;
  }

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({
        url: window.location.href,
        title: document.title,
        html: document.documentElement.outerHTML,
        text: document.body.innerText,
      }),
    });

    if (!result) {
      await showOrUpdateToast(tab.id, "Capture failed", "Could not read this page.", "error");
      return;
    }

    const response = await fetch(CAPTURE_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`,
      },
      body: JSON.stringify(result),
    });

let data: any = null;

try {
  data = await response.json();
} catch {
  data = null;
}

if (response.status === 409) {
  let title = "Job already captured";
  let message = data?.message || "This job already exists.";

  if (data?.status === "failed_existing") {
    title = "Job processing failed earlier";
    message = "Open report and click Retry.";
  } else if (data?.status === "queued") {
    title = "Job already queued";
  } else if (data?.status === "processing") {
    title = "Job already processing";
  } else if (data?.status === "already_processed") {
    title = "Job already in report";
  }

  await showOrUpdateToast(tab.id, title, message, "error");
  return;
}

if (!response.ok) {
  await showOrUpdateToast(
    tab.id,
    "Capture failed",
    data?.detail || `FastAPI returned HTTP ${response.status}.`,
    "error"
  );
  return;
}

    await showOrUpdateToast(
      tab.id,
      "Job captured",
      data?.job_uid ? `Saved as ${data.job_uid}.` : "Job parsed and ranked successfully.",
      "success",
      true
    );
  } catch (error) {
    console.error("Extension capture error:", error);

    await showOrUpdateToast(
      tab.id,
      "Capture failed",
      "FastAPI may not be running at 127.0.0.1:8000.",
      "error"
    );
  }
});
