# Chat API Documentation

Base URL:
- /api

Authentication:
- Use JWT Bearer authentication.
- Header: `Authorization: Bearer <access_token>`

---

## 1. Overview

This API supports two chat types:

- Inquiry chat: used before booking for a mentor.
- Session chat: used after a booking/session is confirmed and paid.

The backend enforces participant access, conversation reuse, and message limits.

---

## 2. Conversation Types

### Inquiry chat
- Used for pre-booking conversations with a mentor.
- Only mentees can start an inquiry conversation.
- Reuses an existing open inquiry conversation with the same mentor/mentee if one exists.
- Message sending is limited by the mentor’s configured pre-booking limit.

### Session chat
- Used for an existing mentorship session.
- Only allowed when the session is paid/confirmed enough to support chat.
- Reuses an existing open session conversation for the same session if one exists.

---

## 3. Endpoints

### 3.1 List conversations
GET /api/conversations/

Headers:
- Authorization: Bearer <token>

Response example:
```json
{
  "results": [
    {
      "id": 1,
      "type": "inquiry",
      "status": "open",
      "mentor_id": 2,
      "mentee_id": 3,
      "session_id": null,
      "other_user_id": 2,
      "other_user_name": "Jane Mentor",
      "last_message": "Hello",
      "last_message_at": "2026-07-26T10:00:00Z",
      "updated_at": "2026-07-26T10:00:00Z"
    }
  ]
}
```

---

### 3.2 Create or reuse a conversation
POST /api/conversations/

Headers:
- Authorization: Bearer <token>

#### Inquiry conversation request
```json
{
  "type": "inquiry",
  "mentor_id": 2
}
```

#### Session conversation request
```json
{
  "type": "session",
  "session_id": 10
}
```

Success response:
```json
{
  "id": 12,
  "type": "inquiry",
  "status": "open"
}
```

Behavior:
- If an open conversation already exists, the backend returns it with status 200.
- If a new conversation is created, the backend returns 201.

Possible errors:
- 400: invalid or missing input
- 403: not allowed for the current user or chat type
- 404: mentor or session not found

---

### 3.3 Get conversation details
GET /api/conversations/{conversation_id}/

Headers:
- Authorization: Bearer <token>

Response example:
```json
{
  "id": 12,
  "type": "inquiry",
  "status": "open",
  "mentor_id": 2,
  "mentee_id": 3,
  "session_id": null,
  "messages": [
    {
      "id": 44,
      "sender_id": 3,
      "sender_name": "John Mentee",
      "body": "Hi, I’d like to ask about your mentorship",
      "created_at": "2026-07-26T10:00:00Z",
      "read_at": null
    }
  ]
}
```

---

### 3.4 Delete conversation
DELETE /api/conversations/{conversation_id}/

Headers:
- Authorization: Bearer <token>

Response:
```json
{
  "deleted": true
}
```

---

### 3.5 List or send messages
GET/POST /api/conversations/{conversation_id}/messages/

Headers:
- Authorization: Bearer <token>

#### Send a message
Request:
```json
{
  "body": "Hello mentor"
}
```

Success response:
```json
{
  "message_id": 88,
  "created_at": "2026-07-26T10:05:00Z"
}
```

#### List messages
Response:
```json
{
  "messages": [
    {
      "id": 44,
      "sender_id": 3,
      "sender_name": "John Mentee",
      "body": "Hello mentor",
      "created_at": "2026-07-26T10:05:00Z",
      "read_at": null
    }
  ]
}
```

Possible errors:
- 400: empty message body
- 403: conversation is closed or message limit exceeded

---

## 4. Business Rules

### Inquiry chat rules
- Only mentees can start inquiry chats.
- The mentor must allow pre-booking messages.
- An existing open inquiry conversation is reused.
- A message limit is enforced per inquiry conversation.
- Default limit is 3 messages.

### Session chat rules
- Session chat is only available for a session that is paid/confirmed enough to support chat.
- The user must be either the mentee or the mentor of that session.

---

## 5. Conversation and Message Fields

### Conversation object
```json
{
  "id": 1,
  "type": "inquiry",
  "status": "open",
  "mentor_id": 2,
  "mentee_id": 3,
  "session_id": null,
  "other_user_id": 2,
  "other_user_name": "Jane Mentor",
  "last_message": "Hello",
  "last_message_at": "2026-07-26T10:00:00Z",
  "updated_at": "2026-07-26T10:00:00Z"
}
```

### Message object
```json
{
  "id": 44,
  "sender_id": 3,
  "sender_name": "John Mentee",
  "body": "Hello mentor",
  "created_at": "2026-07-26T10:05:00Z",
  "read_at": null
}
```

---

## 6. Frontend Implementation Notes

Recommended flow:
1. Load conversations with GET /api/conversations/.
2. When opening chat, create or reuse a conversation:
   - Inquiry: POST /api/conversations/ with `{ "type": "inquiry", "mentor_id": <mentorId> }`
   - Session: POST /api/conversations/ with `{ "type": "session", "session_id": <sessionId> }`
3. Load messages with GET /api/conversations/{conversationId}/messages/.
4. Send messages with POST /api/conversations/{conversationId}/messages/.

---

## 7. Suggested Error Handling

Frontend should handle:
- 401 Unauthorized: token expired or missing
- 403 Forbidden: not allowed to access or send message
- 400 Bad Request: missing required fields
- 404 Not Found: conversation/session/mentor not found

If you want, I can also convert this into a cleaner Markdown file for Slack/Notion-style sharing or generate a TypeScript API client stub for the frontend team.
