use std::collections::HashMap;
use std::collections::HashSet;
use std::error::Error;
use std::io;

pub fn main() {
    if let Err(_e) = run() {
        panic!("failed.");
    }
}

fn run() -> Result<(), Box<Error>> {
    let mut input = String::new();
    io::stdin().read_line(&mut input);
    let nm: Vec<i64> = input
        .trim()
        .split_whitespace()
        .map(|s| s.parse::<i64>().unwrap())
        .collect();
    let n = nm[0];
    let m = nm[1];
    input.clear();

    let mut edges = HashMap::new();
    for _i in 0..n - 1 {
        io::stdin().read_line(&mut input);
        let edge: Vec<i64> = input
            .trim()
            .split_whitespace()
            .map(|s| s.parse::<i64>().unwrap())
            .collect();
        {
            let tos: &mut HashSet<i64> = edges.entry(edge[0]).or_insert_with(HashSet::new);
            tos.insert(edge[1]);
        }
        {
            let tos: &mut HashSet<i64> = edges.entry(edge[1]).or_insert_with(HashSet::new);
            tos.insert(edge[0]);
        }

        input.clear();
    }
    fast_dp(n, m, &edges);
    // slow_dp(n, m, &mut edges);
    Ok(())
}

fn fast_dp(n: i64, m: i64, edges: &HashMap<i64, HashSet<i64>>) {
    let mut dp: HashMap<i64, HashMap<i64, i64>> = HashMap::new();
    dfs(&mut dp, -1, 1, m, edges);
    reverse(&mut dp, -1, 1, m, edges, 0);

    for i in 1..n + 1 {
        let mut result = 1;
        if let Some(dp) = dp.get(&i) {
            for (&to, &value) in dp {
                result *= (value + 1);
                result %= m;
            }
        }
        println!("{}", result);
    }
}

fn dfs(
    dp: &mut HashMap<i64, HashMap<i64, i64>>,
    from: i64,
    to: i64,
    m: i64,
    edges: &HashMap<i64, HashSet<i64>>,
) -> i64 {
    let mut result = 1;
    if let Some(tos) = edges.get(&to) {
        for &x in tos {
            if x != from {
                // 1 is if the next node is white case
                let value = dfs(dp, to, x, m, edges);
                dp.entry(to).or_insert_with(HashMap::new).insert(x, value);
                result *= (value + 1);
                result %= m;
            }
        }
    }
    result
}

fn reverse(
    dp: &mut HashMap<i64, HashMap<i64, i64>>,
    from: i64,
    to: i64,
    m: i64,
    edges: &HashMap<i64, HashSet<i64>>,
    result: i64,
) {
    if let Some(tos) = edges.get(&to) {
        for &x in tos {
            if x == from {
                dp.entry(to)
                    .or_insert_with(HashMap::new)
                    .insert(from, result);
                break;
            }
        }

        let mut l = vec![0; tos.len()];
        let mut r = vec![0; tos.len()];

        for (index, &x) in tos.iter().enumerate() {
            r[index] = (get_dp(&dp, to, x) + 1) % m;
            l[index] = r[index];
        }

        for i in 1..tos.len() {
            l[i] *= l[i - 1];
            l[i] %= m;
        }
        for i in (0..tos.len() - 1).rev() {
            r[i] *= r[i + 1];
            r[i] %= m;
        }

        for (index, &x) in tos.iter().enumerate() {
            if x == from {
                continue;
            }
            let mut result = 1;
            if index != 0 {
                result *= l[index - 1];
                result %= m;
            }
            if index != tos.len() - 1 {
                result *= r[index + 1];
                result %= m;
            }
            reverse(dp, to, x, m, edges, result);
        }
    }
}

fn get_dp(dp: &HashMap<i64, HashMap<i64, i64>>, from: i64, to: i64) -> i64 {
    if let Some(map) = dp.get(&from) {
        if let Some(&value) = map.get(&to) {
            return value;
        }
    }
    panic!("weird.")
}
//
// fn slow_dp(n: i64, m: i64, edges: &mut HashMap<i64, HashSet<i64>>) {
//     // dp from -> to -> variations(is_black)
//     let mut dp: HashMap<i64, HashMap<i64, HashMap<bool, i64>>> = HashMap::new();
//     for i in 1..n + 1 {
//         if !edges.contains_key(&i) {
//             println!("{}", 1 % m);
//             continue;
//         }
//
//         let targets = edges.get(&i).unwrap();
//         let mut result = 1;
//         for &to in targets {
//             let mut sub_result = 0;
//             sub_result += solve_dp(i, to, true, m, &mut dp, &edges);
//             sub_result %= m;
//             sub_result += solve_dp(i, to, false, m, &mut dp, &edges);
//             sub_result %= m;
//             result *= sub_result;
//             result %= m;
//         }
//         println!("{}", result);
//     }
// }
//
// fn solve_dp(
//     from: i64,
//     to: i64,
//     is_black: bool,
//     m: i64,
//     dp: &mut HashMap<i64, HashMap<i64, HashMap<bool, i64>>>,
//     edges: &HashMap<i64, HashSet<i64>>,
// ) -> i64 {
//     if !is_black {
//         return 1;
//     }
//     if !edges.contains_key(&to) {
//         return 1;
//     }
//     if let Some(map) = dp.get(&from) {
//         if let Some(map) = map.get(&to) {
//             if let Some(&value) = map.get(&is_black) {
//                 return value;
//             }
//         }
//     }
//
//     let mut result = 1;
//     let tos = edges.get(&to).unwrap();
//     for &next in tos {
//         if from == next {
//             continue;
//         }
//         let mut sub_result = 0;
//         if is_black {
//             sub_result += solve_dp(to, next, true, m, dp, edges);
//             sub_result %= m;
//         }
//         sub_result += solve_dp(to, next, false, m, dp, edges);
//         sub_result %= m;
//         result *= sub_result;
//         result %= m;
//     }
//     let value = dp
//         .entry(from)
//         .or_insert(HashMap::new())
//         .entry(to)
//         .or_insert(HashMap::new())
//         .entry(is_black)
//         .or_insert(0);
//     *value = result;
//     result
// }
