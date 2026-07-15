# Human Handoffs

Use this reference when a user must choose, authorize, authenticate, provide a secret, perform a
physical/account-owner action, confirm destruction, or leave while work continues.

## Make the Human Edge Small

Avoid a handoff when an available tool or authenticated integration can complete it. When user
involvement is genuinely required:

1. Complete every independent step first.
2. Ask at the moment the missing edge becomes necessary, not at the start of the workflow.
3. Request one smallest action or decision.
4. Give a recommended path, exact command or control when possible, the expected result, and the
   minimal value or signal the user should return.
5. Preserve created files, IDs, decisions, and the next step so work resumes without requiring
   the user to restate the task.

Explain the purpose in user terms. Expose internal tool names only when they help the user
operate, inspect, or recover the workflow.

## Interaction Types

- **Choice:** recommend a safe default and explain the one material tradeoff. Ask one focused
  question only when different answers materially change the result; otherwise choose a
  reversible default and state it briefly.
- **Login or authorization:** say which system or browser will open, what permission is being
  requested, and what success looks like. Keep all local preparation complete and resume from
  the preserved state after authorization.
- **Secret:** ask the user to place it in a named environment variable or secret store. Never ask
  them to paste it into chat or commit it to the workspace. Verify presence without echoing the
  value, then continue from the prepared step. The requested return signal is only that the
  secret has been set; never list the secret value itself as the information the user should send.
- **2FA, CAPTCHA, device, or account-owner action:** identify the exact control, expected screen
  or output, and the simple confirmation needed to resume.
- **Destructive or externally visible action:** inspect or prepare a dry-run/preview first when
  practical. Obtain confirmation when the request has not already granted the relevant
  authority, then execute and verify the result.
- **Long wait:** state whether a real process, goal, schedule, or event source is running. Give a
  status/recovery command and do not claim you will continue or notify later without an actual
  continuity and delivery mechanism.

## Report State, Not Reassurance

At a pause, distinguish clearly between completed work, active work, and the one blocked edge.
For persistent work, report:

- what is running and who owns it;
- identifiers needed to recover it;
- where state and logs live;
- how results will arrive;
- how to pause, stop, or remove it;
- the exact condition that resumes agent work.

A good handoff is a typed interface: the user performs one understandable action, returns one
predictable result, and nanobot continues immediately. Do not offload capability discovery,
implementation design, or repeated mechanical setup to the user.
