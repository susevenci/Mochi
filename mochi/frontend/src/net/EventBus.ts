/** 前端内部事件总线：Live2D 层与 UI 层解耦（计划书 4.4）。 */
type Handler = (payload: unknown) => void;

export class EventBus<Events extends Record<string, unknown>> {
  private readonly handlers = new Map<keyof Events, Set<Handler>>();

  on<K extends keyof Events>(event: K, handler: (payload: Events[K]) => void): () => void {
    const set = this.handlers.get(event) ?? new Set<Handler>();
    set.add(handler as Handler);
    this.handlers.set(event, set);
    return () => set.delete(handler as Handler);
  }

  emit<K extends keyof Events>(event: K, payload: Events[K]): void {
    this.handlers.get(event)?.forEach((handler) => handler(payload));
  }
}
