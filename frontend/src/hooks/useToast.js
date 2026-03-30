import { useState, useCallback, useRef } from 'react';

let nextId = 1;

export function useToast() {
  const [toasts, setToasts] = useState([]);
  const timers = useRef({});

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    if (timers.current[id]) {
      clearTimeout(timers.current[id]);
      delete timers.current[id];
    }
  }, []);

  const addToast = useCallback(
    (type, title, message, duration = 4000) => {
      const id = nextId++;
      setToasts((prev) => [...prev, { id, type, title, message }]);
      if (duration > 0) {
        timers.current[id] = setTimeout(() => removeToast(id), duration);
      }
      return id;
    },
    [removeToast]
  );

  return { toasts, addToast, removeToast };
}
