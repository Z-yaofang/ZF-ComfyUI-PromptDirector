import { app } from "/scripts/app.js";

const EXTENSION_NAME = "ZF.PromptDirector.ZFI";
const NODE_TYPE = "ZFI";
const MAX_CHANNELS = 32;

const clampCount = value => Math.max(1, Math.min(MAX_CHANNELS, Math.round(Number(value) || 1)));

function labelsFor(value, count) {
  const raw = String(value || "").trim();
  const hasExplicitChannels = /\r?\n|[|,，;；]/.test(raw);
  if (raw && !hasExplicitChannels) {
    return Array.from({ length: count }, (_, index) => `${raw}${index + 1}`);
  }
  const labels = raw
    .split(/\r?\n|[|,，;；]/)
    .map(label => label.trim());
  return Array.from({ length: count }, (_, index) => labels[index] || String(index + 1));
}

function graphLink(graph, linkId) {
  if (!graph || linkId == null) return null;
  if (typeof graph.getLink === "function") return graph.getLink(linkId);
  if (graph.links instanceof Map) return graph.links.get(linkId) || null;
  return graph.links?.[linkId] || null;
}

app.registerExtension({
  name: EXTENSION_NAME,
  registerCustomNodes() {
    class ZFIRerouteNode extends LiteGraph.LGraphNode {
      constructor() {
        super("ZFI");
        this.title = "ZFI";
        this.isVirtualNode = true;
        this.serialize_widgets = true;
        this.properties ||= {};

        this.__zfiCountWidget = this.addWidget(
          "number",
          "转接数量",
          3,
          value => {
            this.__zfiCountWidget.value = clampCount(value);
            this.__zfiSyncChannels();
          },
          { min: 1, max: MAX_CHANNELS, step: 1, precision: 0 },
        );
        this.__zfiNotesWidget = this.addWidget(
          "text",
          "通道名称",
          "",
          value => {
            this.__zfiNotesWidget.value = String(value ?? "");
            this.__zfiSyncChannels();
          },
        );
        this.__zfiSyncChannels();
      }

      __zfiSyncChannels() {
        const count = clampCount(this.__zfiCountWidget?.value);
        if (this.__zfiCountWidget) this.__zfiCountWidget.value = count;
        const notes = String(this.__zfiNotesWidget?.value ?? "");
        const labels = labelsFor(notes, count);

        while ((this.inputs?.length || 0) > count) this.removeInput(this.inputs.length - 1);
        while ((this.outputs?.length || 0) > count) this.removeOutput(this.outputs.length - 1);

        for (let index = 0; index < count; index++) {
          if (!this.inputs?.[index]) this.addInput(`input_${index + 1}`, "*");
          if (!this.outputs?.[index]) this.addOutput(`output_${index + 1}`, "*");
          this.inputs[index].name = `input_${index + 1}`;
          this.inputs[index].label = labels[index];
          this.inputs[index].type = "*";
          this.outputs[index].name = `output_${index + 1}`;
          this.outputs[index].label = labels[index];
          this.outputs[index].type = "*";
        }

        this.properties.zfi = {
          version: 1,
          channel_count: count,
          channel_notes: notes,
        };
        this.title = `ZFI · ${count} 路转接`;
        const computed = this.computeSize?.();
        if (computed) {
          const width = Math.max(240, Number(this.size?.[0]) || 0, Number(computed[0]) || 0);
          this.setSize?.([width, Math.max(90, Number(computed[1]) || 0)]);
        }
        this.graph?.setDirtyCanvas?.(true, true);
        this.setDirtyCanvas?.(true, true);
      }

      onConfigure(info) {
        const saved = info?.properties?.zfi;
        if (!Array.isArray(info?.widgets_values) && saved) {
          this.__zfiCountWidget.value = clampCount(saved.channel_count);
          this.__zfiNotesWidget.value = String(saved.channel_notes ?? "");
        }
        this.__zfiSyncChannels();
      }

      onSerialize(info) {
        this.__zfiSyncChannels();
        info.properties ||= {};
        info.properties.zfi = { ...this.properties.zfi };
      }

      onAfterGraphConfigured() {
        this.__zfiSyncChannels();
      }

      resolveVirtualOutput(outputSlot) {
        const link = graphLink(this.graph, this.inputs?.[outputSlot]?.link);
        if (!link) return null;
        const node = this.graph?.getNodeById?.(link.origin_id);
        return node ? { node, slot: link.origin_slot } : null;
      }
    }

    ZFIRerouteNode.title = "ZFI";
    ZFIRerouteNode.category = "ZF/提示词创意导演/流程工具";
    ZFIRerouteNode.prototype.comfyClass = NODE_TYPE;
    LiteGraph.registerNodeType(NODE_TYPE, ZFIRerouteNode);
  },
});
