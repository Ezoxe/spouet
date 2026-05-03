// Évite l'ouverture d'une console Windows derrière l'app en release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    spouet_desktop_lib::run()
}
