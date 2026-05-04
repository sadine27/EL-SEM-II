const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const WORKFLOW_PATH = path.join(ROOT, "el_workflow.json");
const ENV_PATH = path.join(ROOT, ".env");
const WORKFLOW_ID = "298f3JSOE72nhW59";
const HIL_CHAT_ID = "8243518279";

const TELEGRAM_CREDENTIAL = {
  telegramApi: {
    id: "5w4zQqucsn6Vehh6",
    name: "EL-HIL-BOT",
  },
};

const POSTGRES_CREDENTIAL = {
  postgres: {
    id: "Tx3i0fewZ8MM6LFt",
    name: "Supabase yatralounge (Dropship Memory)",
  },
};

const telegramCardPrepJs = String.raw`
const CHAT_ID = '8243518279';
const MAX_CAPTION_LENGTH = 900;

function compact(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

function escapeHtml(value) {
  return compact(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function truncate(value, maxLength) {
  const text = compact(value);
  return text.length > maxLength ? text.slice(0, maxLength - 3) + '...' : text;
}

function money(row) {
  const priceText = compact(row.price_text);
  if (priceText) return priceText;
  const numeric = Number(row.price_numeric);
  if (!Number.isFinite(numeric)) return 'price n/a';
  const currency = compact(row.currency).toUpperCase();
  if (currency === 'INR') return 'INR ' + numeric;
  return currency ? String(numeric) + ' ' + currency : String(numeric);
}

function rating(row) {
  const value = Number(row.product_rating);
  if (!Number.isFinite(value)) return 'rating n/a';
  const reviews = Number(row.reviews_count);
  return Number.isFinite(reviews) ? String(value) + '/5 (' + reviews + ')' : String(value) + '/5';
}

function source(row) {
  return compact(row.marketplace || row.source_provider || 'source n/a');
}

function buildCallback(action, row) {
  const payload = action + ':' + row.id + ':' + row.callback_token;
  if (Buffer.byteLength(payload, 'utf8') > 64) {
    throw new Error('Telegram callback payload is over 64 bytes for review ' + row.id);
  }
  return payload;
}

function buildCaption(row) {
  const name = escapeHtml(truncate(row.product_name, 140));
  const price = escapeHtml(money(row));
  const score = row.raw_payload?.phase4_selection?.confidence_score ?? row.raw_payload?.phase4_debug?.score ?? null;
  const scoreText = score == null ? '' : '\nScore: <b>' + escapeHtml(score) + '</b>';
  const lines = [
    '<b>' + name + '</b>',
    'Price: <b>' + price + '</b>',
    'Rating: ' + escapeHtml(rating(row)),
    'Source: ' + escapeHtml(source(row)),
    'Topic: ' + escapeHtml(truncate(row.source_topic, 120)),
    scoreText.trim(),
  ].filter(Boolean);
  return truncate(lines.join('\n'), MAX_CAPTION_LENGTH);
}

return $input.all().map((item) => {
  const row = item.json || {};
  const caption = buildCaption(row);
  const text = caption + '\n\nImage unavailable: sending text card.';
  return {
    json: {
      ...row,
      review_id: row.id,
      telegram_chat_id: CHAT_ID,
      telegram_caption: caption,
      telegram_text: text,
      telegram_file_name: 'hil-review-' + (row.id || 'item') + '.jpg',
      telegram_approve_callback: buildCallback('a', row),
      telegram_reject_callback: buildCallback('r', row),
      telegram_skip_callback: buildCallback('s', row),
      image_url: compact(row.image_url),
    },
  };
});
`;

const parseCallbackJs = String.raw`
const ZERO_UUID = '00000000-0000-0000-0000-000000000000';

function compact(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

function sanitizeParam(value, maxLength = 120) {
  return compact(value)
    .replace(/[,\r\n<>]/g, ' ')
    .replace(/\s+/g, ' ')
    .slice(0, maxLength);
}

function actorLabel(user) {
  if (!user) return '';
  if (user.username) return '@' + sanitizeParam(user.username, 64).replace(/^@+/, '');
  const name = sanitizeParam([user.first_name, user.last_name].filter(Boolean).join(' '), 80);
  return name || sanitizeParam(user.id, 40);
}

function parsePayload(data) {
  const parts = compact(data).split(':');
  const valid = parts.length === 3
    && /^[ars]$/.test(parts[0])
    && /^\d{1,19}$/.test(parts[1])
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(parts[2]);
  return {
    valid,
    action_code: valid ? parts[0] : 'x',
    review_id: valid ? parts[1] : '0',
    callback_token: valid ? parts[2].toLowerCase() : ZERO_UUID,
  };
}

return $input.all().map((item) => {
  const update = item.json || {};
  const callback = update.callback_query || {};
  const from = callback.from || {};
  const message = callback.message || {};
  const chat = message.chat || {};
  const parsed = parsePayload(callback.data);
  const data = compact(callback.data);
  return {
    json: {
      ...parsed,
      callback_query_id: sanitizeParam(callback.id, 120),
      callback_data: sanitizeParam(data, 80),
      callback_payload_valid: parsed.valid,
      actor_id: sanitizeParam(from.id, 40),
      actor_label: actorLabel(from),
      chat_id: sanitizeParam(chat.id, 40),
      message_id: sanitizeParam(message.message_id, 40),
      message_has_photo: Array.isArray(message.photo) && message.photo.length > 0,
      message_text_preview: sanitizeParam(message.text || message.caption || '', 180),
    },
  };
});
`;

const applyCallbackSql = String.raw`
WITH payload AS (
  SELECT
    CASE $1::text
      WHEN 'a' THEN 'approved'
      WHEN 'r' THEN 'rejected'
      WHEN 's' THEN 'skipped'
      ELSE NULL
    END AS target_status,
    $1::text AS action_code,
    $2::bigint AS review_id,
    $3::uuid AS callback_token,
    NULLIF($4::text, '') AS actor_id,
    NULLIF($5::text, '') AS actor_label,
    $6::text AS callback_query_id,
    NULLIF($7::text, '')::bigint AS chat_id,
    NULLIF($8::text, '')::bigint AS message_id,
    $9::text AS callback_data
),
matched AS (
  SELECT h.*
  FROM private.hil_reviews h
  JOIN payload p
    ON h.id = p.review_id
   AND h.callback_token = p.callback_token
),
updated AS (
  UPDATE private.hil_reviews h
  SET approval_status = p.target_status,
      reviewed_by = COALESCE(p.actor_label, p.actor_id, 'telegram_user'),
      reviewed_at = now(),
      updated_at = now()
  FROM payload p
  WHERE h.id = p.review_id
    AND h.callback_token = p.callback_token
    AND h.approval_status = 'pending'
    AND p.target_status IS NOT NULL
  RETURNING h.id, h.approval_status, h.reviewed_by, h.reviewed_at
),
callback_event AS (
  INSERT INTO private.hil_review_events (
    review_id,
    event_type,
    actor_type,
    actor_id,
    payload
  )
  SELECT
    m.id,
    'callback_received',
    'telegram_user',
    p.actor_id,
    jsonb_build_object(
      'action_code', p.action_code,
      'target_status', p.target_status,
      'callback_query_id', p.callback_query_id,
      'chat_id', p.chat_id,
      'message_id', p.message_id,
      'callback_data', p.callback_data,
      'was_pending', m.approval_status = 'pending'
    )
  FROM matched m
  CROSS JOIN payload p
  WHERE p.target_status IS NOT NULL
  RETURNING id
),
action_event AS (
  INSERT INTO private.hil_review_events (
    review_id,
    event_type,
    actor_type,
    actor_id,
    payload
  )
  SELECT
    u.id,
    u.approval_status,
    'telegram_user',
    p.actor_id,
    jsonb_build_object(
      'callback_query_id', p.callback_query_id,
      'chat_id', p.chat_id,
      'message_id', p.message_id,
      'reviewed_by', u.reviewed_by,
      'reviewed_at', u.reviewed_at
    )
  FROM updated u
  CROSS JOIN payload p
  RETURNING id
)
SELECT
  COALESCE(u.id, m.id, p.review_id) AS review_id,
  p.callback_query_id,
  p.chat_id,
  p.message_id,
  COALESCE(u.approval_status, m.approval_status, 'invalid') AS approval_status,
  COALESCE(u.reviewed_by, m.reviewed_by, p.actor_label, p.actor_id, 'telegram_user') AS reviewed_by,
  COALESCE(u.reviewed_at, m.reviewed_at, now()) AS reviewed_at,
  (u.id IS NOT NULL) AS message_should_finalize,
  CASE
    WHEN p.target_status IS NULL THEN 'Invalid review action.'
    WHEN u.id IS NOT NULL THEN initcap(u.approval_status) || ' recorded.'
    WHEN m.id IS NOT NULL THEN 'Already reviewed: ' || m.approval_status || '.'
    ELSE 'Review token is invalid or expired.'
  END AS callback_answer_text,
  CASE
    WHEN u.id IS NOT NULL THEN
      '<b>Review ' || u.approval_status || '</b>' ||
      E'\nID: <code>' || u.id::text || '</code>' ||
      E'\nBy: ' || COALESCE(u.reviewed_by, 'telegram_user')
    ELSE NULL
  END AS telegram_edit_text
FROM payload p
LEFT JOIN matched m ON true
LEFT JOIN updated u ON true;
`;

function buildLogMessageFinalizedSql(method) {
  return `
INSERT INTO private.hil_review_events (
  review_id,
  event_type,
  actor_type,
  actor_id,
  payload
)
VALUES (
  $1::bigint,
  'message_edited',
  'workflow',
  'workflow',
  jsonb_build_object(
    'method', '${method}',
    'chat_id', $2::bigint,
    'message_id', $3::bigint,
    'callback_query_id', $4::text
  )
)
RETURNING id, review_id, event_type, event_at;
`;
}

function replaceNodeDefinition(workflow, nodeName, nodeDef) {
  const index = workflow.nodes.findIndex((entry) => entry.name === nodeName);
  if (index === -1) {
    workflow.nodes.push(nodeDef);
    return;
  }
  workflow.nodes[index] = { ...workflow.nodes[index], ...nodeDef };
}

function replaceConnection(workflow, sourceName, connection) {
  workflow.connections[sourceName] = connection;
}

function readEnv() {
  const env = {};
  const raw = fs.readFileSync(ENV_PATH, "utf8");
  for (const lineRaw of raw.split(/\r?\n/)) {
    const line = lineRaw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const idx = line.indexOf("=");
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, "");
    env[key] = value;
  }
  return env;
}

function exportCleanWorkflow(workflow) {
  const omit = new Set([
    "updatedAt",
    "createdAt",
    "shared",
    "versionId",
    "activeVersionId",
    "versionCounter",
    "triggerCount",
    "tags",
    "parentFolder",
    "activeVersion",
  ]);
  return Object.fromEntries(Object.entries(workflow).filter(([key]) => !omit.has(key)));
}

function inlineKeyboard() {
  return {
    rows: [
      {
        row: {
          buttons: [
            {
              text: "Approve",
              additionalFields: {
                callback_data: "={{ $('Prepare Telegram Card').item.json.telegram_approve_callback }}",
              },
            },
            {
              text: "Reject",
              additionalFields: {
                callback_data: "={{ $('Prepare Telegram Card').item.json.telegram_reject_callback }}",
              },
            },
            {
              text: "Skip",
              additionalFields: {
                callback_data: "={{ $('Prepare Telegram Card').item.json.telegram_skip_callback }}",
              },
            },
          ],
        },
      },
      {
        row: {
          buttons: [
            {
              text: "Open Product",
              additionalFields: {
                url: "={{ $('Prepare Telegram Card').item.json.product_url }}",
              },
            },
          ],
        },
      },
    ],
  };
}

function applyPhase6(workflow) {
  const next = JSON.parse(JSON.stringify(workflow));

  replaceNodeDefinition(next, "Prepare Telegram Card", {
    parameters: {
      jsCode: telegramCardPrepJs,
    },
    type: "n8n-nodes-base.code",
    typeVersion: 2,
    position: [3024, 1216],
    id: "p4tg-prep-0001",
    name: "Prepare Telegram Card",
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "Send HIL Telegram Photo", {
    parameters: {
      resource: "message",
      operation: "sendPhoto",
      chatId: HIL_CHAT_ID,
      binaryData: true,
      binaryPropertyName: "product_image",
      replyMarkup: "inlineKeyboard",
      inlineKeyboard: inlineKeyboard(),
      additionalFields: {
        caption: "={{ $('Prepare Telegram Card').item.json.telegram_caption }}",
        parse_mode: "HTML",
        fileName: "={{ $('Prepare Telegram Card').item.json.telegram_file_name }}",
      },
    },
    type: "n8n-nodes-base.telegram",
    typeVersion: 1.2,
    position: [3472, 1120],
    id: "p4tg-photo-0001",
    name: "Send HIL Telegram Photo",
    webhookId: "p4tg-photo-webhook-0001",
    credentials: TELEGRAM_CREDENTIAL,
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "Send HIL Telegram Text Fallback", {
    parameters: {
      resource: "message",
      operation: "sendMessage",
      chatId: HIL_CHAT_ID,
      text: "={{ $('Prepare Telegram Card').item.json.telegram_text }}",
      replyMarkup: "inlineKeyboard",
      inlineKeyboard: inlineKeyboard(),
      additionalFields: {
        appendAttribution: false,
        disable_web_page_preview: false,
        parse_mode: "HTML",
      },
    },
    type: "n8n-nodes-base.telegram",
    typeVersion: 1.2,
    position: [3472, 1328],
    id: "p4tg-text-0001",
    name: "Send HIL Telegram Text Fallback",
    webhookId: "p4tg-text-webhook-0001",
    credentials: TELEGRAM_CREDENTIAL,
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "Mark Telegram Text Fallback", {
    parameters: {
      operation: "executeQuery",
      query: "UPDATE private.hil_reviews\nSET telegram_chat_id = $2::bigint,\n    telegram_message_id = $3::bigint,\n    telegram_media_status = 'text_only',\n    telegram_sent_at = now(),\n    updated_at = now()\nWHERE id = $1::bigint\nRETURNING id, telegram_chat_id, telegram_message_id, telegram_media_status, telegram_sent_at;",
      options: {
        queryReplacement: "={{ $('Prepare Telegram Card').item.json.review_id }},{{ $json.result.chat.id }},{{ $json.result.message_id }}",
        queryBatching: "independently",
      },
    },
    type: "n8n-nodes-base.postgres",
    typeVersion: 2.5,
    position: [3696, 1328],
    id: "p4tg-mark-text-0001",
    name: "Mark Telegram Text Fallback",
    credentials: POSTGRES_CREDENTIAL,
    continueOnFail: true,
  });

  replaceNodeDefinition(next, "Telegram Trigger", {
    parameters: {
      updates: ["callback_query"],
      additionalFields: {},
    },
    type: "n8n-nodes-base.telegramTrigger",
    typeVersion: 1.2,
    position: [3024, 1664],
    id: "p6tg-trigger-0001",
    name: "Telegram Trigger",
    webhookId: "p6tg-trigger-webhook-0001",
    credentials: TELEGRAM_CREDENTIAL,
  });

  replaceNodeDefinition(next, "Parse HIL Callback", {
    parameters: {
      jsCode: parseCallbackJs,
    },
    type: "n8n-nodes-base.code",
    typeVersion: 2,
    position: [3248, 1664],
    id: "p6tg-parse-0001",
    name: "Parse HIL Callback",
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "Apply HIL Callback", {
    parameters: {
      operation: "executeQuery",
      query: applyCallbackSql,
      options: {
        queryReplacement: "={{ $json.action_code }},{{ $json.review_id }},{{ $json.callback_token }},{{ $json.actor_id }},{{ $json.actor_label }},{{ $json.callback_query_id }},{{ $json.chat_id }},{{ $json.message_id }},{{ $json.callback_data }}",
        queryBatching: "independently",
      },
    },
    type: "n8n-nodes-base.postgres",
    typeVersion: 2.5,
    position: [3472, 1664],
    id: "p6tg-apply-0001",
    name: "Apply HIL Callback",
    credentials: POSTGRES_CREDENTIAL,
  });

  replaceNodeDefinition(next, "Answer HIL Callback", {
    parameters: {
      resource: "callback",
      operation: "answerQuery",
      queryId: "={{ $('Apply HIL Callback').item.json.callback_query_id }}",
      additionalFields: {
        text: "={{ $('Apply HIL Callback').item.json.callback_answer_text }}",
        show_alert: false,
        cache_time: 0,
      },
    },
    type: "n8n-nodes-base.telegram",
    typeVersion: 1.2,
    position: [3696, 1664],
    id: "p6tg-answer-0001",
    name: "Answer HIL Callback",
    credentials: TELEGRAM_CREDENTIAL,
  });

  replaceNodeDefinition(next, "If Callback Finalized Review", {
    parameters: {
      conditions: {
        options: {
          caseSensitive: true,
          leftValue: "",
          typeValidation: "strict",
          version: 1,
        },
        conditions: [
          {
            id: "callback-finalized-review",
            leftValue: "={{ $('Apply HIL Callback').item.json.message_should_finalize ? 1 : 0 }}",
            rightValue: 1,
            operator: {
              type: "number",
              operation: "equals",
            },
          },
        ],
        combinator: "and",
      },
      options: {},
    },
    type: "n8n-nodes-base.if",
    typeVersion: 2.2,
    position: [3920, 1664],
    id: "p6tg-if-finalized-0001",
    name: "If Callback Finalized Review",
  });

  replaceNodeDefinition(next, "Edit HIL Review Message", {
    parameters: {
      resource: "message",
      operation: "editMessageText",
      messageType: "message",
      chatId: "={{ $('Apply HIL Callback').item.json.chat_id }}",
      messageId: "={{ $('Apply HIL Callback').item.json.message_id }}",
      replyMarkup: "none",
      text: "={{ $('Apply HIL Callback').item.json.telegram_edit_text }}",
      additionalFields: {
        disable_web_page_preview: true,
        parse_mode: "HTML",
      },
    },
    type: "n8n-nodes-base.telegram",
    typeVersion: 1.2,
    position: [4144, 1568],
    id: "p6tg-edit-0001",
    name: "Edit HIL Review Message",
    credentials: TELEGRAM_CREDENTIAL,
    onError: "continueErrorOutput",
  });

  replaceNodeDefinition(next, "Log HIL Message Edited", {
    parameters: {
      operation: "executeQuery",
      query: buildLogMessageFinalizedSql("editMessageText"),
      options: {
        queryReplacement: "={{ $('Apply HIL Callback').item.json.review_id }},{{ $('Apply HIL Callback').item.json.chat_id }},{{ $('Apply HIL Callback').item.json.message_id }},{{ $('Apply HIL Callback').item.json.callback_query_id }}",
        queryBatching: "independently",
      },
    },
    type: "n8n-nodes-base.postgres",
    typeVersion: 2.5,
    position: [4368, 1504],
    id: "p6tg-log-edit-0001",
    name: "Log HIL Message Edited",
    credentials: POSTGRES_CREDENTIAL,
    continueOnFail: true,
  });

  replaceNodeDefinition(next, "Delete HIL Review Message After Edit Failure", {
    parameters: {
      resource: "message",
      operation: "deleteMessage",
      chatId: "={{ $('Apply HIL Callback').item.json.chat_id }}",
      messageId: "={{ $('Apply HIL Callback').item.json.message_id }}",
    },
    type: "n8n-nodes-base.telegram",
    typeVersion: 1.2,
    position: [4368, 1648],
    id: "p6tg-delete-0001",
    name: "Delete HIL Review Message After Edit Failure",
    credentials: TELEGRAM_CREDENTIAL,
    continueOnFail: true,
  });

  replaceNodeDefinition(next, "Log HIL Message Deleted", {
    parameters: {
      operation: "executeQuery",
      query: buildLogMessageFinalizedSql("deleteMessageAfterEditFailure"),
      options: {
        queryReplacement: "={{ $('Apply HIL Callback').item.json.review_id }},{{ $('Apply HIL Callback').item.json.chat_id }},{{ $('Apply HIL Callback').item.json.message_id }},{{ $('Apply HIL Callback').item.json.callback_query_id }}",
        queryBatching: "independently",
      },
    },
    type: "n8n-nodes-base.postgres",
    typeVersion: 2.5,
    position: [4592, 1648],
    id: "p6tg-log-delete-0001",
    name: "Log HIL Message Deleted",
    credentials: POSTGRES_CREDENTIAL,
    continueOnFail: true,
  });

  replaceNodeDefinition(next, "cluster:phase6-telegram-callbacks", {
    parameters: {
      content: "## Phase 6 - Telegram Callback Review\n\nReview cards now carry compact inline callback payloads: `a:<review_id>:<callback_token>`, `r:<review_id>:<callback_token>`, and `s:<review_id>:<callback_token>`.\nThe callback branch validates the row/token, updates only pending reviews, writes review events, answers Telegram, and finalizes the original message by editing text or deleting the photo card if Telegram cannot edit it.",
      height: 420,
      width: 1696,
      color: 4,
    },
    type: "n8n-nodes-base.stickyNote",
    typeVersion: 1,
    position: [2976, 1488],
    id: "p6tg-sticky-0001",
    name: "cluster:phase6-telegram-callbacks",
  });

  replaceConnection(next, "Telegram Trigger", {
    main: [
      [
        {
          node: "Parse HIL Callback",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Parse HIL Callback", {
    main: [
      [
        {
          node: "Apply HIL Callback",
          type: "main",
          index: 0,
        },
      ],
      [
        {
          node: "Error Formatter",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Apply HIL Callback", {
    main: [
      [
        {
          node: "Answer HIL Callback",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Answer HIL Callback", {
    main: [
      [
        {
          node: "If Callback Finalized Review",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "If Callback Finalized Review", {
    main: [
      [
        {
          node: "Edit HIL Review Message",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Edit HIL Review Message", {
    main: [
      [
        {
          node: "Log HIL Message Edited",
          type: "main",
          index: 0,
        },
      ],
      [
        {
          node: "Delete HIL Review Message After Edit Failure",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  replaceConnection(next, "Delete HIL Review Message After Edit Failure", {
    main: [
      [
        {
          node: "Log HIL Message Deleted",
          type: "main",
          index: 0,
        },
      ],
    ],
  });

  return next;
}

async function getLiveWorkflow(env) {
  const res = await fetch(env.N8N_URL + "/api/v1/workflows/" + WORKFLOW_ID, {
    headers: { "X-N8N-API-KEY": env.N8N_SECRET, Accept: "application/json" },
  });
  if (!res.ok) throw new Error("GET workflow failed: " + res.status + " " + await res.text());
  return res.json();
}

async function putLiveWorkflow(env, workflow) {
  const workflowSettings = workflow.settings || {};
  const body = {
    name: workflow.name,
    nodes: workflow.nodes,
    connections: workflow.connections,
    settings: Object.fromEntries(
      Object.entries({
        executionOrder: workflowSettings.executionOrder || "v1",
        errorWorkflow: workflowSettings.errorWorkflow || undefined,
      }).filter(([, value]) => value != null)
    ),
  };
  const res = await fetch(env.N8N_URL + "/api/v1/workflows/" + WORKFLOW_ID, {
    method: "PUT",
    headers: {
      "X-N8N-API-KEY": env.N8N_SECRET,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("PUT workflow failed: " + res.status + " " + await res.text());
  return res.json();
}

async function activateLiveWorkflow(env, workflow) {
  const body = workflow.versionId ? { versionId: workflow.versionId } : {};
  const res = await fetch(env.N8N_URL + "/api/v1/workflows/" + WORKFLOW_ID + "/activate", {
    method: "POST",
    headers: {
      "X-N8N-API-KEY": env.N8N_SECRET,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Activate workflow failed: " + res.status + " " + await res.text());
  return res.json();
}

async function main() {
  const applyLive = process.argv.includes("--live");
  const localWorkflow = JSON.parse(fs.readFileSync(WORKFLOW_PATH, "utf8"));
  const patchedLocal = applyPhase6(localWorkflow);
  fs.writeFileSync(WORKFLOW_PATH, JSON.stringify(patchedLocal, null, 2) + "\n", "utf8");
  console.log("Phase 6 Telegram callbacks added to local el_workflow.json");

  if (!applyLive) return;

  const env = readEnv();
  const liveWorkflow = await getLiveWorkflow(env);
  const wasActive = Boolean(liveWorkflow.active);
  const patchedLive = applyPhase6(liveWorkflow);
  const updatedLive = await putLiveWorkflow(env, patchedLive);
  if (wasActive) {
    await activateLiveWorkflow(env, updatedLive);
  }

  const refreshed = await getLiveWorkflow(env);
  fs.writeFileSync(WORKFLOW_PATH, JSON.stringify(exportCleanWorkflow(refreshed), null, 2) + "\n", "utf8");
  console.log("Phase 6 Telegram callbacks applied to live n8n workflow");
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
