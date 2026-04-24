// State
let currentDate = new Date();

// DOM elements
const loadingEl = document.getElementById('loading');
const errorEl = document.getElementById('error');
const dashboardEl = document.getElementById('dashboard');
const lastUpdatedEl = document.getElementById('lastUpdated');
const currentDateEl = document.getElementById('currentDate');
const prevDayBtn = document.getElementById('prevDay');
const nextDayBtn = document.getElementById('nextDay');
const doneItemsEl = document.getElementById('doneItems');
const inProgressItemsEl = document.getElementById('inProgressItems');
const upNextItemsEl = document.getElementById('upNextItems');
const slackItemsEl = document.getElementById('slackItems');
const slackWorkItemsEl = document.getElementById('slackWorkItems');
const warningsBannerEl = document.getElementById('warningsBanner');
const standupDigestEl = document.getElementById('standupDigest');
const digestYesterdayEl = document.getElementById('digestYesterday');
const digestTodayEl = document.getElementById('digestToday');
const digestBlockersEl = document.getElementById('digestBlockers');

// Max pills to show per section before collapsing into "... +N more"
const MAX_PILLS_PER_SECTION = 10;

// Utility functions
function formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function formatDisplayDate(date) {
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    return date.toLocaleDateString('en-US', options);
}

function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    const options = {
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short'
    };
    return date.toLocaleString('en-US', options);
}

function isWeekend(date) {
    const day = date.getDay();
    return day === 0 || day === 6; // Sunday or Saturday
}

function getPreviousWorkday(date) {
    const prev = new Date(date);
    prev.setDate(prev.getDate() - 1);

    // Skip weekends
    while (isWeekend(prev)) {
        prev.setDate(prev.getDate() - 1);
    }

    return prev;
}

function getNextWorkday(date) {
    const next = new Date(date);
    next.setDate(next.getDate() + 1);

    // Skip weekends
    while (isWeekend(next)) {
        next.setDate(next.getDate() + 1);
    }

    return next;
}

// Render functions
function createPill(item, type) {
    const pill = document.createElement('a');
    pill.href = item.url;
    pill.className = `pill ${type}`;
    pill.target = '_blank';
    pill.rel = 'noopener noreferrer';

    // Determine display text based on item type
    let displayText;
    if (item.key) {
        // Jira or GitHub item
        const isCodeReview = item.source === 'github' && type === 'up-next';
        const prefix = isCodeReview ? '[review] ' : '';
        displayText = `${prefix}${item.key}: ${item.summary}`;
    } else if (item.channel) {
        // Slack attention item
        const ageText = item.age ? ` (${item.age})` : '';
        displayText = `${item.channel}: ${item.summary}${ageText}`;
    } else if (item.context) {
        // Slack work-mining item
        const ageText = item.age ? ` (${item.age})` : '';
        displayText = `${item.context}: ${item.summary}${ageText}`;
    } else {
        displayText = item.summary;
    }

    pill.textContent = displayText;

    // Add tooltip with description
    if (item.description) {
        const tooltip = document.createElement('span');
        tooltip.className = 'tooltip';
        tooltip.textContent = item.description;
        pill.appendChild(tooltip);
    }

    return pill;
}

function renderSection(container, items, type) {
    container.innerHTML = '';

    if (!items || items.length === 0) {
        return; // Empty state handled by CSS
    }

    const visible = items.slice(0, MAX_PILLS_PER_SECTION);
    const hiddenCount = items.length - visible.length;

    visible.forEach(item => {
        const pill = createPill(item, type);
        container.appendChild(pill);
    });

    if (hiddenCount > 0) {
        const more = document.createElement('span');
        more.className = 'more-indicator';
        more.textContent = `… and ${hiddenCount} more`;
        container.appendChild(more);
    }
}

function renderDigest(digest) {
    if (!digest || typeof digest !== 'object') {
        standupDigestEl.style.display = 'none';
        return;
    }

    const sections = [
        [digestYesterdayEl, digest.yesterday],
        [digestTodayEl, digest.today],
        [digestBlockersEl, digest.blockers],
    ];

    let anyContent = false;
    sections.forEach(([ul, items]) => {
        ul.innerHTML = '';
        if (Array.isArray(items) && items.length > 0) {
            anyContent = true;
            items.forEach(text => {
                const li = document.createElement('li');
                li.textContent = text;
                ul.appendChild(li);
            });
        }
    });

    standupDigestEl.style.display = anyContent ? 'block' : 'none';
}

function renderDashboard(data) {
    renderDigest(data.standup_digest);
    renderSection(doneItemsEl, data.done, 'done');
    renderSection(inProgressItemsEl, data.in_progress, 'in-progress');
    renderSection(upNextItemsEl, data.up_next, 'up-next');
    renderSection(slackItemsEl, data.slack_attention, 'slack');
    renderSection(slackWorkItemsEl, data.slack_work, 'slack-work');

    if (Array.isArray(data.warnings) && data.warnings.length > 0) {
        const ul = document.createElement('ul');
        data.warnings.forEach(w => {
            const li = document.createElement('li');
            li.textContent = w;
            ul.appendChild(li);
        });
        warningsBannerEl.innerHTML = '';
        warningsBannerEl.appendChild(ul);
        warningsBannerEl.style.display = 'block';
    } else {
        warningsBannerEl.style.display = 'none';
    }

    if (data.generated_at) {
        lastUpdatedEl.textContent = `Last updated: ${formatTimestamp(data.generated_at)}`;
    } else {
        lastUpdatedEl.textContent = '';
    }
}

// Data fetching
async function fetchData(date, retries = 5) {
    const dateStr = formatDate(date);
    const url = `data/${dateStr}.json`;

    try {
        const response = await fetch(url);

        if (!response.ok) {
            if (response.status === 404 && retries > 0) {
                // Try previous workday
                const prevDay = getPreviousWorkday(date);
                return fetchData(prevDay, retries - 1);
            }
            throw new Error(`Failed to load data: ${response.status}`);
        }

        const data = await response.json();
        return { data, date };
    } catch (error) {
        if (retries > 0) {
            const prevDay = getPreviousWorkday(date);
            return fetchData(prevDay, retries - 1);
        }
        throw error;
    }
}

async function loadDashboard(date) {
    // Show loading state
    loadingEl.style.display = 'block';
    errorEl.style.display = 'none';
    dashboardEl.style.display = 'none';
    warningsBannerEl.style.display = 'none';
    standupDigestEl.style.display = 'none';

    try {
        const result = await fetchData(date);

        if (!result) {
            throw new Error('No data available');
        }

        // Update current date to the one we actually loaded
        currentDate = result.date;
        currentDateEl.textContent = formatDisplayDate(currentDate);

        // Render the dashboard
        renderDashboard(result.data);

        // Show dashboard
        loadingEl.style.display = 'none';
        dashboardEl.style.display = 'flex';
    } catch (error) {
        console.error('Error loading dashboard:', error);
        loadingEl.style.display = 'none';
        errorEl.style.display = 'block';
        errorEl.textContent = `No data available for recent workdays. ${error.message}`;
    }
}

// Event listeners
prevDayBtn.addEventListener('click', () => {
    const prevDay = getPreviousWorkday(currentDate);
    loadDashboard(prevDay);
});

nextDayBtn.addEventListener('click', () => {
    const nextDay = getNextWorkday(currentDate);

    // Don't go into the future beyond today
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const nextDayStart = new Date(nextDay);
    nextDayStart.setHours(0, 0, 0, 0);

    if (nextDayStart <= today) {
        loadDashboard(nextDay);
    }
});

// Initialize on page load
window.addEventListener('DOMContentLoaded', () => {
    loadDashboard(currentDate);
});
