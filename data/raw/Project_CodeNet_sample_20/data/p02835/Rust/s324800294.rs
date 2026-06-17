#[allow(unused_imports)]
use proconio::{fastout, input, marker::*};

#[fastout]
fn main() {
    input! {
        a: [usize; 3],
    }

    println!("{}", if 22 <= a.iter().sum::<usize>() { "bust" } else { "win" });
}
