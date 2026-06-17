use proconio::input;

fn cal(mut x: u64) -> u64 {
    let mut ans = 0;
    while 0 != x {
        ans += x % 10;
        x /= 10;
    }
    ans
}

fn main() {
    let mut snuke = vec![];
    let mut ten_p = 1;
    for p in 0..16 {
        for k in std::iter::successors(Some(0), |k| Some(k + 1))
            .filter(|k| k % 10 != 9)
            .take_while(|&k| (k + 1) * ten_p - 1 <= (cal(k) + 9 * p) * ten_p)
        {
            snuke.push(ten_p * (k + 1) - 1);
        }
        ten_p *= 10;
    }
    snuke.sort();

    input!(k: usize);
    for &x in snuke.iter().skip(1).take(k) {
        println!("{}", x);
    }
}
