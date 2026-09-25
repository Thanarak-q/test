import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

export const Dialog = ({
  title,
  children,
  onClose,
  dismissible = true,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  dismissible?: boolean;
}) => {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    const previousFocus = document.activeElement;
    if (dialog) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    return () => {
      if (dialog?.open) {
        if (typeof dialog.close === "function") dialog.close();
        else dialog.removeAttribute("open");
      }
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={titleId}
      onClick={(event) => {
        if (dismissible && event.target === event.currentTarget) onClose();
      }}
      onCancel={(event) => {
        event.preventDefault();
        if (dismissible) onClose();
      }}
    >
      <div className="modal-header">
        <h2 id={titleId}>{title}</h2>
        {dismissible && (
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close dialog">
            <X />
          </button>
        )}
      </div>
      {children}
    </dialog>
  );
};
