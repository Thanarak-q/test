import { Select } from "@base-ui/react/select";
import { Check, ChevronDown } from "lucide-react";

export const FilterSelect = <Value extends string>({
  label,
  value,
  options,
  onValueChange,
  className = "",
}: {
  label: string;
  value: Value;
  options: { value: Value; label: string }[];
  onValueChange: (value: Value) => void;
  className?: string;
}) => (
  <Select.Root
    items={options}
    value={value}
    onValueChange={(next) => {
      if (next !== null) onValueChange(next);
    }}
  >
    <Select.Trigger className={`filter-select ${className}`} aria-label={label}>
      <Select.Value className="filter-select-value" />
      <Select.Icon className="filter-select-icon">
        <ChevronDown />
      </Select.Icon>
    </Select.Trigger>
    <Select.Portal>
      <Select.Positioner
        className="select-positioner"
        sideOffset={6}
        align="start"
        alignItemWithTrigger={false}
      >
        <Select.Popup className="select-popup" aria-label={label}>
          <Select.List className="select-list">
            {options.map((option) => (
              <Select.Item key={option.value} value={option.value} className="select-item">
                <Select.ItemText>{option.label}</Select.ItemText>
                <Select.ItemIndicator className="select-indicator">
                  <Check />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.List>
        </Select.Popup>
      </Select.Positioner>
    </Select.Portal>
  </Select.Root>
);
