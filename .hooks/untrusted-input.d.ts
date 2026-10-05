interface Body {
  json(): Promise<unknown>;
}

interface JSON {
  parse(
    text: string,
    reviver?: {
      revive(this: unknown, key: string, value: unknown): unknown;
    }["revive"],
  ): unknown;
}

interface ArrayConstructor {
  isArray<T>(
    arg: T,
  ): arg is Extract<T, readonly unknown[]> extends never
    ? unknown extends T
      ? T & unknown[]
      : {} extends T
        ? T & unknown[]
        : T & any[]
    : Extract<T, readonly unknown[]>;
}

interface ObjectConstructor {
  values<T>(o: { [s: string]: T } | ArrayLike<T>): T[];
  values(o: {}): unknown[];
  entries<T>(o: { [s: string]: T } | ArrayLike<T>): [string, T][];
  entries(o: {}): [string, unknown][];
}
