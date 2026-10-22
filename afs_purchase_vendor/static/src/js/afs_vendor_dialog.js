/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { RelationalModel } from "@web/model/relational_model/relational_model";

export class AfsVendorDialog extends Component {
    static template = "afs_purchase_vendor.AfsVendorDialog";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        message: { type: String, optional: true },
        close: Function,
    };

    accept() {
        this.props.close({ afsAccept: true });
    }
}

patch(RelationalModel.prototype, {
    _displayOnchangeWarning(warning) {
        if (warning?.type?.startsWith("afs_accept")) {
            Promise.resolve(this.hooks.onWillDisplayOnchangeWarning(warning)).then(() => {
                this.dialog.add(
                    AfsVendorDialog,
                    { title: warning.title, message: warning.message },
                    {
                        // Weigeren of het kruisje: terug naar de leverancier van het product
                        onClose: (params) => {
                            if (!params?.afsAccept) {
                                const [, id, ...name] = warning.type.split(":");
                                return this.root.update({
                                    partner_id: id ? { id: parseInt(id), display_name: name.join(":") } : false,
                                });
                            }
                        },
                    }
                );
            });
            return;
        }
        return super._displayOnchangeWarning(...arguments);
    },
});
