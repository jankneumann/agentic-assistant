# persona-registry Delta

## ADDED Requirements

### Requirement: Extension Initialization and Shutdown Lifecycle

The persona registry SHALL drive the optional extension lifecycle
hooks around `load_extensions()`:

- **Initialization**: for each extension instance produced during
  loading, the registry SHALL call the extension's `initialize()`
  hook (when present and callable) in `PersonaConfig.extensions`
  declaration order, immediately post-load. The registry SHALL await
  the hook's result only when it is awaitable, tolerating synchronous
  hooks on out-of-tree extensions. An extension without the hook is
  loaded as before.
- **Failure isolation**: when `initialize()` raises, the registry
  SHALL log a WARNING identifying the extension and the error,
  attempt a best-effort `shutdown()` of the failed instance (errors
  swallowed), exclude that extension from the returned list, and
  continue loading the remaining extensions. Persona load MUST NOT
  fail because one extension failed to initialize.
- **Async variant**: the registry SHALL provide
  `load_extensions_async(config)` for callers already running inside
  an event loop. The synchronous `load_extensions(config)` SHALL
  execute the identical load+initialize pipeline via `asyncio.run()`
  when no event loop is running, and SHALL raise a `RuntimeError`
  naming `load_extensions_async` when called while a loop is running.
- **Shutdown registration**: extensions returned by a load SHALL be
  tracked as active. The registry SHALL register a process-exit
  (`atexit`) handler at most once per registry instance, and SHALL
  provide an explicit async `shutdown_extensions()` that calls each
  active extension's `shutdown()` hook (when present) in reverse
  activation order, swallowing and WARNING-logging per-extension
  errors. `shutdown_extensions()` MUST be idempotent — a second call
  after a completed shutdown is a no-op.

#### Scenario: initialize called post-load in declaration order

- **WHEN** `load_extensions()` runs for a persona declaring
  extensions `a` then `b`, both defining `initialize()`
- **THEN** `a.initialize()` MUST be awaited before `b.initialize()`
- **AND** both instances MUST appear in the returned list

#### Scenario: failing initialize disables only that extension

- **WHEN** extension `a`'s `initialize()` raises and sibling `b`'s
  succeeds
- **THEN** `load_extensions()` MUST NOT raise
- **AND** the returned list MUST contain `b` but not `a`
- **AND** a WARNING naming `a` MUST be logged

#### Scenario: extension without hooks loads unchanged

- **WHEN** a loaded extension defines no lifecycle hooks
- **THEN** `load_extensions()` MUST return it without warnings about
  missing hooks

#### Scenario: sync load_extensions rejects a running event loop

- **WHEN** `load_extensions()` is called from a coroutine running in
  an event loop
- **THEN** a `RuntimeError` MUST be raised
- **AND** the message MUST name `load_extensions_async`

#### Scenario: shutdown_extensions runs hooks in reverse order and is idempotent

- **WHEN** extensions `a` then `b` were activated and
  `await shutdown_extensions()` is called
- **THEN** `b.shutdown()` MUST be awaited before `a.shutdown()`
- **AND** a second `await shutdown_extensions()` MUST complete
  without calling any hook again

#### Scenario: shutdown hook failure is contained

- **WHEN** `b.shutdown()` raises during `shutdown_extensions()`
- **THEN** `a.shutdown()` MUST still be awaited
- **AND** a WARNING naming `b` MUST be logged
